import calendar
from decimal import Decimal
from datetime import date, datetime
from typing import List, Dict, Any, Optional
from sqlmodel import Session, select, func
from app.domain.dates import add_months, month_key
from app.domain.query_policy import REALIZED_STATUSES, workspace_base_currency
from app.models.transaction import (
    SplitMode,
    Transaction,
    TransactionItem,
    TransactionItemShare,
    TransactionSplit,
)
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
        # Despesa recorta por billing_month — a MESMA definição de mês que
        # Lançamentos e Dívidas usam. Ver domain.dates.month_key.
        mes = month_key(target_month)

        # Total de despesas — política única de status/moeda (ADR 0003/0006).
        # Tudo em Decimal: float() perdia centavos (REL-001).
        expenses = db.exec(
            select(func.sum(Transaction.total_amount))
            .where(Transaction.workspace_id == workspace_id)
            .where(Transaction.billing_month == mes)
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
                .where(Transaction.billing_month == mes)
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
            .where(Transaction.billing_month == mes)
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

        # Distribuição por categoria da MINHA parte — o par de `categories` para
        # a meta pessoal. Sem isto, a meta por categoria do usuário só poderia ser
        # comparada com o gasto da casa, que é exatamente o erro que o orçamento
        # com escopo veio corrigir.
        my_category_data: List[Dict[str, Any]] = []
        if user_id is not None:
            my_categorized = ReportService._my_categorized(
                db, workspace_id, mes, base_currency, user_id
            )
            my_category_data = [
                {
                    "category_id": cid,
                    "name": category_names.get(cid, "Categoria"),
                    "value": valor,
                }
                for cid, valor in sorted(my_categorized.items(), key=lambda kv: kv[0])
            ]
            my_categorized_total = sum(
                (v for v in my_categorized.values()), Decimal("0.00")
            )
            my_uncategorized = my_expenses - my_categorized_total
            if my_uncategorized > 0:
                my_category_data.append(
                    {"category_id": None, "name": "Sem categoria", "value": my_uncategorized}
                )

        # Lançamentos em moeda diferente da base ficam FORA dos totais (ADR 0006).
        # Expor a contagem deixa o usuário saber que "sumiram" de propósito (E5/F-04).
        excluded_foreign_count = db.exec(
            select(func.count(Transaction.id))
            .where(Transaction.workspace_id == workspace_id)
            .where(Transaction.billing_month == mes)
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
            # Mesma composição, recortada na parte do usuário (meta pessoal)
            "my_categories": my_category_data,
            "base_currency": base_currency,
            "excluded_foreign_count": excluded_foreign_count,
        }

    @staticmethod
    def _my_categorized(
        db: Session,
        workspace_id: int,
        mes: str,
        base_currency: str,
        user_id: int,
    ) -> Dict[int, Decimal]:
        """Quanto do gasto de `user_id` no mês caiu em cada categoria.

        Duas fontes, porque a "minha parte de um item" só é explícita num modo:

        - `split_mode='item'`: a share do usuário no item JÁ é o valor dele
          naquela linha (`TransactionItemShare.computed_amount`). Exato.
        - `split_mode='transaction'`: a divisão é da despesa inteira, não por
          linha. Rateamos a parte do usuário (`TransactionSplit.computed_amount`)
          proporcionalmente ao valor dos itens, em centavos exatos
          (`_allocate_proportional`, ADR 0001) — nenhum centavo se perde nem se
          inventa. Na prática também é exato: nesse modo existe no máximo o
          item-categoria único, cujo valor É o total.
        """
        por_categoria: Dict[int, Decimal] = {}

        def _somar(category_id, valor: Decimal) -> None:
            if category_id is None or valor == 0:
                return
            por_categoria[category_id] = por_categoria.get(category_id, Decimal("0.00")) + valor

        base = (
            select(Transaction.id, Transaction.split_mode)
            .where(Transaction.workspace_id == workspace_id)
            .where(Transaction.billing_month == mes)
            .where(Transaction.deleted_at.is_(None))
            .where(Transaction.status.in_(REALIZED_STATUSES))
            .where(Transaction.currency == base_currency)
        )
        modo_por_tx = dict(db.exec(base).all())
        if not modo_por_tx:
            return por_categoria

        tx_ids = list(modo_por_tx)
        item_mode_ids = [
            tid for tid, modo in modo_por_tx.items() if modo == SplitMode.item
        ]

        # (1) modo item: a share do usuário por linha, direto
        if item_mode_ids:
            linhas = db.exec(
                select(TransactionItem.category_id, TransactionItemShare.computed_amount)
                .join(TransactionItemShare, TransactionItemShare.item_id == TransactionItem.id)
                .where(TransactionItem.transaction_id.in_(item_mode_ids))
                .where(TransactionItemShare.user_id == user_id)
            ).all()
            for category_id, valor in linhas:
                _somar(category_id, valor or Decimal("0.00"))

        # (2) modo transaction: rateia a parte do usuário pelos itens da despesa
        outros_ids = [tid for tid in tx_ids if tid not in set(item_mode_ids)]
        if not outros_ids:
            return por_categoria

        minha_parte = dict(db.exec(
            select(TransactionSplit.transaction_id, TransactionSplit.computed_amount)
            .where(TransactionSplit.transaction_id.in_(outros_ids))
            .where(TransactionSplit.user_id == user_id)
        ).all())
        if not minha_parte:
            return por_categoria

        itens_por_tx: Dict[int, List] = {}
        for item in db.exec(
            select(TransactionItem)
            .where(TransactionItem.transaction_id.in_(list(minha_parte)))
            .order_by(TransactionItem.position, TransactionItem.id)
        ).all():
            itens_por_tx.setdefault(item.transaction_id, []).append(item)

        for tx_id, parte in minha_parte.items():
            itens = itens_por_tx.get(tx_id)
            if not itens:
                continue  # sem item = sem categoria; cai em "Sem categoria"
            pesos = {i: _cents(item.amount) for i, item in enumerate(itens)}
            if sum(pesos.values()) <= 0:
                pesos = {i: 1 for i in range(len(itens))}
            alocado = _allocate_proportional(_cents(parte), pesos)
            for i, item in enumerate(itens):
                _somar(item.category_id, Decimal(alocado[i]) / Decimal("100"))

        return por_categoria

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
        month_keys = [month_key(d) for d in months]

        window_start = datetime.combine(months[0], datetime.min.time())
        last = months[-1]
        last_day_num = calendar.monthrange(last.year, last.month)[1]
        window_end = datetime.combine(
            date(last.year, last.month, last_day_num), datetime.max.time()
        )

        # Despesa agrupa por billing_month (mesma definição de mês do resto do
        # app); o SQL só filtra os 6 meses e a soma sai em Python — assim não
        # dependemos de strftime (SQLite) nem to_char (Postgres).
        expense_rows = db.exec(
            select(Transaction.billing_month, Transaction.total_amount)
            .where(Transaction.workspace_id == workspace_id)
            .where(Transaction.billing_month.in_(month_keys))
            .where(Transaction.deleted_at.is_(None))
            .where(Transaction.status.in_(REALIZED_STATUSES))
            .where(Transaction.currency == base_currency)
        ).all()
        expenses_by_month: Dict[str, Decimal] = {}
        for key, amount in expense_rows:
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
                select(Transaction.billing_month, TransactionSplit.computed_amount)
                .join(Transaction, Transaction.id == TransactionSplit.transaction_id)
                .where(Transaction.workspace_id == workspace_id)
                .where(Transaction.billing_month.in_(month_keys))
                .where(Transaction.deleted_at.is_(None))
                .where(Transaction.status.in_(REALIZED_STATUSES))
                .where(Transaction.currency == base_currency)
                .where(TransactionSplit.user_id == user_id)
            ).all()
            for key, amount in my_rows:
                my_by_month[key] = my_by_month.get(key, Decimal("0.00")) + amount

        # `month` (YYYY-MM) é o rótulo AUTORITATIVO: `name` vinha de
        # `strftime("%b")`, que usa o locale do processo — no container (locale C)
        # o eixo dos gráficos de Relatórios falava inglês ("Jan/Feb/May") num app
        # inteiro em PT-BR. O nome fica por compatibilidade; quem desenha formata
        # a partir de `month` com Intl.
        return [
            {
                "month": key,
                "name": d.strftime("%b"),
                "expenses": expenses_by_month.get(key, Decimal("0.00")),
                "income": income_by_month.get(key, Decimal("0.00")),
                "my_expenses": my_by_month.get(key, Decimal("0.00")),
            }
            for d, key in zip(months, month_keys)
        ]
