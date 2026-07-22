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
        category_data = [
            {"name": category_names.get(cid, "Categoria"), "value": amount or Decimal("0.00")}
            for cid, amount in categorized
        ]
        categorized_total = sum((amount or Decimal("0.00") for _, amount in categorized), Decimal("0.00"))
        uncategorized = expenses - categorized_total
        if uncategorized > 0:
            category_data.append({"name": "Sem categoria", "value": uncategorized})

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
        db: Session, workspace_id: int, user_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        results = []
        first_of_month = date.today().replace(day=1)
        for i in range(5, -1, -1):
            d = add_months(first_of_month, -i)  # mês de calendário, não days=30
            summary = ReportService.get_summary(db, workspace_id, d, user_id=user_id)
            results.append({
                "name": d.strftime("%b"),
                "expenses": summary["total_expenses"],
                "income": summary["total_income"],
                "my_expenses": summary["my_expenses"],
            })
        return results
