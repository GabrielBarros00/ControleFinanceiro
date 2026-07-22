from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, date
from typing import Dict, Any
from sqlmodel import Session, select, func
from app.domain.query_policy import (
    FORECAST_STATUSES,
    workspace_base_currency,
)
from app.models.transaction import Transaction
from app.models.recurring import RecurringExpense, RecurringIncome, RecurrenceFrequency
from app.models.estimate import MonthlyEstimate
from app.models.income import Income
from app.models.credit_card import CreditCard, CardStatement, StatementStatus
from app.services.credit_card_service import CreditCardService
from app.services.recurring_service import RecurringService
import calendar

class ForecastService:
    @staticmethod
    def get_monthly_projection(
        db: Session,
        workspace_id: int,
        target_month: date
    ) -> Dict[str, Any]:
        """
        Calculates a predictive forecast for the end of the month.
        """
        base_currency = workspace_base_currency(db, workspace_id)
        # 1. Current spent (Transactions in the month)
        first_day = date(target_month.year, target_month.month, 1)
        last_day_num = calendar.monthrange(target_month.year, target_month.month)[1]
        last_day = date(target_month.year, target_month.month, last_day_num)
        
        # Gastos em dinheiro do mês. Transações vinculadas a fatura de cartão
        # (statement_id) ficam FORA do fluxo de caixa: o evento de caixa é a
        # fatura no vencimento (evita contagem dupla).
        transactions = db.exec(
            select(Transaction)
            .where(Transaction.workspace_id == workspace_id)
            .where(Transaction.transaction_date >= datetime.combine(first_day, datetime.min.time()))
            .where(Transaction.transaction_date <= datetime.combine(last_day, datetime.max.time()))
            .where(Transaction.deleted_at.is_(None))
            .where(Transaction.statement_id.is_(None))
            .where(Transaction.status.in_(FORECAST_STATUSES))
            .where(Transaction.currency == base_currency)
        ).all()

        total_spent = sum((t.total_amount for t in transactions), Decimal("0.00"))

        # Faturas de cartão com vencimento neste mês (ainda não pagas) são caixa a sair
        card_statements_due = db.exec(
            select(CardStatement)
            .join(CreditCard, CreditCard.id == CardStatement.card_id)
            .where(CreditCard.workspace_id == workspace_id)
            .where(CardStatement.status != StatementStatus.paid)
            .where(CardStatement.due_date >= datetime.combine(first_day, datetime.min.time()))
            .where(CardStatement.due_date <= datetime.combine(last_day, datetime.max.time()))
        ).all()
        # Fatura ABERTA soma em tempo real; FECHADA usa o total CONGELADO no
        # fechamento (ADR 0011) — a MESMA definição de card_committed/effective_total.
        # Recomputar aqui divergia do valor faturado se uma transação de fatura já
        # fechada fosse editada depois (F-06).
        statements_pending = Decimal("0.00")
        for stmt in card_statements_due:
            statements_pending += CreditCardService.effective_total(db, stmt)
        
        # 2. Daily Average (Trend-based)
        today = date.today()
        if today.month == target_month.month and today.year == target_month.year:
            days_passed = today.day
            remaining_days = last_day_num - days_passed
        elif target_month < today:
            days_passed = last_day_num
            remaining_days = 0
        else:
            days_passed = 0
            remaining_days = last_day_num
            
        daily_avg = (total_spent / days_passed).quantize(Decimal("0.01")) if days_passed > 0 else Decimal("0.00")
        
        # 3. Fixed Costs (Remaining Recurring Expenses)
        recurring = db.exec(
            select(RecurringExpense)
            .where(RecurringExpense.workspace_id == workspace_id)
            .where(RecurringExpense.is_active.is_(True))
        ).all()

        # Ocorrências que JÁ têm instância lançada no mês não entram de novo
        # (a instância já está em total_spent) — evita contagem dupla.
        # Semanal deduplica por data exata; mensal/anual por template no mês.
        billing_month = target_month.strftime("%Y-%m")
        instanced = db.exec(
            select(Transaction.recurring_expense_id, Transaction.transaction_date)
            .where(Transaction.workspace_id == workspace_id)
            .where(Transaction.billing_month == billing_month)
            .where(Transaction.recurring_expense_id.is_not(None))
            .where(Transaction.deleted_at.is_(None))
        ).all()
        instanced_dates = {(rid, dt.date()) for rid, dt in instanced}
        instanced_templates = {rid for rid, _ in instanced}

        # Diária/semanal deduplicam por data exata; mensal/anual por template no mês
        per_occurrence = (RecurrenceFrequency.daily, RecurrenceFrequency.weekly)

        def _occurrence_pending(template: RecurringExpense, occ: date) -> bool:
            if template.frequency in per_occurrence:
                return (template.id, occ) not in instanced_dates
            return template.id not in instanced_templates

        remaining_fixed = Decimal("0.00")
        is_current = today.month == target_month.month and today.year == target_month.year
        if is_current or target_month > today:
            for r in recurring:
                for occ in RecurringService.occurrences_in_month(
                    r, target_month.year, target_month.month
                ):
                    if is_current and occ <= today:
                        continue  # vencida: ou já virou instância, ou generate cobre
                    if _occurrence_pending(r, occ):
                        remaining_fixed += r.base_amount

        # 4. Projected Total (caixa: gastos + tendência + fixos pendentes + faturas a vencer)
        projected_total = total_spent + (daily_avg * remaining_days) + remaining_fixed + statements_pending
        
        # 5. Budget Comparison (Monthly Estimates) — excluídas ficam fora
        estimates = db.exec(
            select(MonthlyEstimate)
            .where(MonthlyEstimate.workspace_id == workspace_id)
            .where(MonthlyEstimate.month == target_month.strftime("%Y-%m"))
            .where(MonthlyEstimate.deleted_at.is_(None))
        ).all()
        
        total_budget = sum(e.amount for e in estimates)

        # 6. Renda do mês (INC-001): a previsão precisa do outro lado do caixa —
        # sobra projetada = renda recebida no mês − gasto projetado
        income_actual = db.exec(
            select(func.sum(Income.amount))
            .where(Income.workspace_id == workspace_id)
            .where(Income.received_at >= datetime.combine(first_day, datetime.min.time()))
            .where(Income.received_at <= datetime.combine(last_day, datetime.max.time()))
            .where(Income.deleted_at.is_(None))
        ).one() or Decimal("0.00")

        # 6b. Rendas recorrentes ainda NÃO materializadas no mês → projeção.
        # Simétrico ao remaining_fixed das despesas: já materializadas contam em
        # income_actual; as pendentes (sem instância) entram como renda esperada.
        income_pending = Decimal("0.00")
        if is_current or target_month > today:
            recurring_incomes = db.exec(
                select(RecurringIncome)
                .where(RecurringIncome.workspace_id == workspace_id)
                .where(RecurringIncome.is_active.is_(True))
            ).all()
            materialized_income = db.exec(
                select(Income.recurring_income_id, Income.received_at)
                .where(Income.workspace_id == workspace_id)
                .where(Income.billing_month == billing_month)
                .where(Income.recurring_income_id.is_not(None))
                .where(Income.deleted_at.is_(None))
            ).all()
            mat_income_dates = {(rid, dt.date()) for rid, dt in materialized_income}
            mat_income_templates = {rid for rid, _ in materialized_income}
            for ri in recurring_incomes:
                for occ in RecurringService.occurrences_in_month(
                    ri, target_month.year, target_month.month
                ):
                    if ri.frequency in per_occurrence:
                        already = (ri.id, occ) in mat_income_dates
                    else:
                        already = ri.id in mat_income_templates
                    if not already:
                        income_pending += ri.base_amount

        projected_income = income_actual + income_pending

        # Lançamentos em moeda estrangeira ficam fora da projeção (ADR 0006);
        # a contagem sinaliza isso ao usuário (E5/F-04).
        excluded_foreign_count = db.exec(
            select(func.count(Transaction.id))
            .where(Transaction.workspace_id == workspace_id)
            .where(Transaction.transaction_date >= datetime.combine(first_day, datetime.min.time()))
            .where(Transaction.transaction_date <= datetime.combine(last_day, datetime.max.time()))
            .where(Transaction.deleted_at.is_(None))
            .where(Transaction.status.in_(FORECAST_STATUSES))
            .where(Transaction.currency != base_currency)
        ).one() or 0

        return {
            "month": target_month.strftime("%Y-%m"),
            "base_currency": base_currency,
            "excluded_foreign_count": excluded_foreign_count,
            "actual_spent": total_spent,
            "projected_eom": projected_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "daily_average": daily_avg,
            "remaining_days": remaining_days,
            "fixed_costs_pending": remaining_fixed,
            "card_statements_pending": statements_pending,
            "total_budget": total_budget,
            "is_over_budget": projected_total > total_budget if total_budget > 0 else False,
            "income_actual": income_actual,
            "income_pending": income_pending,
            "projected_income": projected_income,
            "projected_net": (projected_income - projected_total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        }
