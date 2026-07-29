import calendar
from decimal import Decimal
from datetime import date, datetime
from typing import List, Dict, Any, Optional
from sqlmodel import Session, select, func
from app.domain.dates import add_months
from app.domain.query_policy import REALIZED_STATUSES, workspace_base_currency
from app.models.transaction import Transaction, TransactionItem, TransactionSplit
from app.models.income import Income
from app.models.category import Category
from app.services.transaction_service import _allocate_proportional, _cents


class ReportService:
    @staticmethod
    def get_summary(
        db: Session,
        workspace_id: int,
        target_month: date,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        base_currency = workspace_base_currency(db, workspace_id)
        first_day = date(target_month.year, target_month.month, 1)
        last_day_num = calendar.monthrange(target_month.year, target_month.month)[1]
        last_day = date(target_month.year, target_month.month, last_day_num)
        start = datetime.combine(first_day, datetime.min.time())
        end = datetime.combine(last_day, datetime.max.time())

        # Total de despesas — política única de status/moeda (ADR 0003/0006).
        # Tudo em Decimal: float() perdia centavos (REL-001).
        expenses = db.exec(
            select(func.sum(Transaction.total_amount))
            .where(Transaction.workspace_id == workspace_id)
            .where(Transaction.transaction_date >= start)
            .where(Transaction.transaction_date <= end)
            .where(Transaction.deleted_at.is_(None))
            .where(Transaction.status.in_(REALIZED_STATUSES))
            .where(Transaction.currency == base_currency)
        ).one() or Decimal("0.00")

        income = db.exec(
            select(func.sum(Income.amount))
            .where(Income.workspace_id == workspace_id)
            .where(Income.received_at >= start)
            .where(Income.received_at <= end)
            .where(Income.deleted_at.is_(None))
            # Mesma política de moeda da despesa (ADR 0006). Sem este filtro a
            # renda era o ÚNICO somatório que ignorava a moeda-base: uma renda
            # legada em USD entrava somada a despesas em BRL.
            .where(Income.currency == base_currency)
        ).one() or Decimal("0.00")

        # "Minha parte": recorte por usuário reusando a MESMA política do total.
        # Gasto do usuário = soma dos splits dele (mesma fonte de verdade das
        # dívidas); renda do usuário = suas entradas (Income tem user_id).
        # Sem user_id, os campos "my_*" ficam zerados (visão só da casa).
        my_expenses = Decimal("0.00")
        my_income = Decimal("0.00")
        if user_id is not None:
            my_expenses = db.exec(
                select(func.sum(TransactionSplit.computed_amount))
                .join(Transaction)
                .where(Transaction.workspace_id == workspace_id)
                .where(Transaction.transaction_date >= start)
                .where(Transaction.transaction_date <= end)
                .where(Transaction.deleted_at.is_(None))
                .where(Transaction.status.in_(REALIZED_STATUSES))
                .where(Transaction.currency == base_currency)
                .where(TransactionSplit.user_id == user_id)
            ).one() or Decimal("0.00")

            my_income = db.exec(
                select(func.sum(Income.amount))
                .where(Income.workspace_id == workspace_id)
                .where(Income.received_at >= start)
                .where(Income.received_at <= end)
                .where(Income.deleted_at.is_(None))
                .where(Income.currency == base_currency)
                .where(Income.user_id == user_id)
            ).one() or Decimal("0.00")

        # Distribuição por categoria: soma dos itens COM categoria. Itens sem
        # categoria E transações sem item nenhum entram em "Sem categoria" — que
        # é exatamente (total − categorizado), então nada some do gráfico (REL-001).
        categorized = db.exec(
            select(TransactionItem.category_id, func.sum(TransactionItem.amount))
            .join(Transaction)
            .where(Transaction.workspace_id == workspace_id)
            .where(Transaction.transaction_date >= start)
            .where(Transaction.transaction_date <= end)
            .where(Transaction.deleted_at.is_(None))
            .where(Transaction.status.in_(REALIZED_STATUSES))
            .where(Transaction.currency == base_currency)
            .where(TransactionItem.category_id.is_not(None))
            .group_by(TransactionItem.category_id)
        ).all()

        category_names = {
            c.id: c.name
            for c in db.exec(select(Category).where(Category.workspace_id == workspace_id)).all()
        }
        # O id acompanha o nome: o orçamento casa gasto × meta por category_id
        # (BUD-001) — casar por nome quebrava calado ao renomear a categoria.
        category_data = [
            {
                "category_id": cid,
                "name": category_names.get(cid, "Categoria"),
                "value": amount or Decimal("0.00"),
            }
            for cid, amount in categorized
        ]
        categorized_total = sum((amount or Decimal("0.00") for _, amount in categorized), Decimal("0.00"))
        uncategorized = expenses - categorized_total
        if uncategorized > 0:
            category_data.append({"category_id": None, "name": "Sem categoria", "value": uncategorized})
        elif uncategorized < 0:
            # Itens somam MAIS que o total: acontece com ajuste negativo
            # (desconto/cashback), em que total = itens + ajustes com ajustes < 0.
            # Antes o valor negativo era só descartado e a pizza passava a somar
            # mais que o `total_expenses` exibido ao lado dela. Rateamos a
            # diferença entre as categorias, em centavos exatos, para o gráfico
            # fechar com o total — que é o número que o usuário confere.
            weights = {
                i: _cents(item["value"])
                for i, item in enumerate(category_data)
                if item["value"] > 0
            }
            if weights and sum(weights.values()) > 0:
                alloc = _allocate_proportional(_cents(uncategorized), weights)
                for i, delta in alloc.items():
                    category_data[i]["value"] += Decimal(delta) / Decimal("100")

        # Lançamentos em moeda diferente da base ficam FORA dos totais (ADR 0006).
        # Expor a contagem deixa o usuário saber que "sumiram" de propósito (E5/F-04).
        excluded_foreign_count = db.exec(
            select(func.count(Transaction.id))
            .where(Transaction.workspace_id == workspace_id)
            .where(Transaction.transaction_date >= start)
            .where(Transaction.transaction_date <= end)
            .where(Transaction.deleted_at.is_(None))
            .where(Transaction.status.in_(REALIZED_STATUSES))
            .where(Transaction.currency != base_currency)
        ).one() or 0

        return {
            "total_expenses": expenses,
            "total_income": income,
            "net_savings": income - expenses,
            # Recorte do usuário logado (a parte dele, não o valor cheio da casa)
            "my_expenses": my_expenses,
            "my_income": my_income,
            "my_net": my_income - my_expenses,
            "categories": category_data,
            "base_currency": base_currency,
            "excluded_foreign_count": excluded_foreign_count,
        }

    @staticmethod
    def get_last_6_months(
        db: Session,
        workspace_id: int,
        user_id: Optional[int] = None,
        ref_month: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """6 meses terminando em `ref_month` (padrão: mês corrente).

        Uma query por MÉTRICA agrupando os 6 meses de uma vez, em vez de um
        get_summary completo por mês (que fazia ~5 queries × 6 = 30 idas ao
        banco só para desenhar as barras).
        """
        base_currency = workspace_base_currency(db, workspace_id)
        first_of_month = (ref_month or date.today()).replace(day=1)
        months = [add_months(first_of_month, -i) for i in range(5, -1, -1)]

        window_start = datetime.combine(months[0], datetime.min.time())
        last = months[-1]
        last_day_num = calendar.monthrange(last.year, last.month)[1]
        window_end = datetime.combine(
            date(last.year, last.month, last_day_num), datetime.max.time()
        )

        # func.strftime não existe no Postgres e to_char não existe no SQLite:
        # agrupamos em Python a partir das linhas já filtradas pela janela, que
        # é curta (6 meses) e continua sendo UMA ida ao banco por métrica.
        expense_rows = db.exec(
            select(Transaction.transaction_date, Transaction.total_amount)
            .where(Transaction.workspace_id == workspace_id)
            .where(Transaction.transaction_date >= window_start)
            .where(Transaction.transaction_date <= window_end)
            .where(Transaction.deleted_at.is_(None))
            .where(Transaction.status.in_(REALIZED_STATUSES))
            .where(Transaction.currency == base_currency)
        ).all()
        expenses_by_month: Dict[str, Decimal] = {}
        for dt, amount in expense_rows:
            key = dt.strftime("%Y-%m")
            expenses_by_month[key] = expenses_by_month.get(key, Decimal("0.00")) + amount

        income_rows = db.exec(
            select(Income.received_at, Income.amount)
            .where(Income.workspace_id == workspace_id)
            .where(Income.received_at >= window_start)
            .where(Income.received_at <= window_end)
            .where(Income.deleted_at.is_(None))
            # MESMA política de moeda do get_summary (ADR 0006). Sem este filtro
            # o histórico somava renda legada em outra moeda e o card "Receita"
            # divergia da barra do mesmo mês — na MESMA tela de Relatórios.
            .where(Income.currency == base_currency)
        ).all()
        income_by_month: Dict[str, Decimal] = {}
        for dt, amount in income_rows:
            key = dt.strftime("%Y-%m")
            income_by_month[key] = income_by_month.get(key, Decimal("0.00")) + amount

        my_by_month: Dict[str, Decimal] = {}
        if user_id is not None:
            my_rows = db.exec(
                select(Transaction.transaction_date, TransactionSplit.computed_amount)
                .join(Transaction, Transaction.id == TransactionSplit.transaction_id)
                .where(Transaction.workspace_id == workspace_id)
                .where(Transaction.transaction_date >= window_start)
                .where(Transaction.transaction_date <= window_end)
                .where(Transaction.deleted_at.is_(None))
                .where(Transaction.status.in_(REALIZED_STATUSES))
                .where(Transaction.currency == base_currency)
                .where(TransactionSplit.user_id == user_id)
            ).all()
            for dt, amount in my_rows:
                key = dt.strftime("%Y-%m")
                my_by_month[key] = my_by_month.get(key, Decimal("0.00")) + amount

        # `month` (YYYY-MM) é o rótulo AUTORITATIVO: `name` vinha de
        # `strftime("%b")`, que usa o locale do processo — no container (locale C)
        # o eixo dos gráficos de Relatórios falava inglês ("Jan/Feb/May") num app
        # inteiro em PT-BR. O nome fica por compatibilidade; quem desenha formata
        # a partir de `month` com Intl.
        return [
            {
                "month": d.strftime("%Y-%m"),
                "name": d.strftime("%b"),
                "expenses": expenses_by_month.get(d.strftime("%Y-%m"), Decimal("0.00")),
                "income": income_by_month.get(d.strftime("%Y-%m"), Decimal("0.00")),
                "my_expenses": my_by_month.get(d.strftime("%Y-%m"), Decimal("0.00")),
            }
            for d in months
        ]
