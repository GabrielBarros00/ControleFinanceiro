from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, date
from typing import Any, Dict, Optional
from sqlmodel import Session, select, func
from app.domain.dates import month_key
from app.domain.access_policy import cards_of_workspace, income_of_workspace
from app.domain.query_policy import (
    FORECAST_STATUSES,
    workspace_base_currency,
)
from app.models.transaction import Transaction
from sqlalchemy import or_
from app.models.recurring import (
    RecurrenceFrequency,
    RecurringExpense,
    RecurringIncome,
    RecurringIncomeWorkspaceShare,
)
from app.models.estimate import MonthlyEstimate
from app.models.income import Income
from app.models.credit_card import CreditCard, CardStatement, StatementStatus
from app.services.credit_card_service import CreditCardService
from app.services.currency_service import ExchangeRateUnavailable
from app.services.exchange_rate_store import ExchangeRateStore
from app.services.recurring_service import RecurringService
import calendar

def _template_amount_in_base(db, template, occ: date, base_currency: str):
    """Valor do template na MOEDA-BASE. Devolve (valor, conseguiu_converter).

    Antes a projeção somava `template.base_amount` cru: uma assinatura de
    `USD 100` entrava como `R$ 100` (≈5x menor). Como todo o resto do serviço
    filtra por `currency == base_currency`, os fixos pendentes eram o único
    ponto que ignorava a moeda — e erravam para MENOS, que é o lado perigoso num
    app de orçamento.

    Sem cotação no store, o template fica de fora e é contado como excluído (a
    mesma política do ADR 0006 aplicada às transações). Nunca vai à rede: isto
    roda num GET.
    """
    currency = getattr(template, "currency", None)
    if not currency or currency == base_currency:
        return template.base_amount, True
    try:
        # rate_between: a taxa precisa ser moeda→BASE, e o store só guarda X→BRL
        rate, _ = ExchangeRateStore.rate_between(
            db, currency, base_currency, occ, allow_fetch=False
        )
    except ExchangeRateUnavailable:
        return Decimal("0.00"), False
    return (template.base_amount * rate).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    ), True


class ForecastService:
    @staticmethod
    def get_monthly_projection(
        db: Session,
        workspace_id: int,
        target_month: date,
        user_id: Optional[int] = None,
        full_access: bool = True,
    ) -> Dict[str, Any]:
        """
        Calculates a predictive forecast for the end of the month.

        A previsão é, por natureza, projeção de CAIXA DA CASA: gasto do mês,
        média diária, fixos a vencer, faturas pendentes, renda e sobra. Nada disso
        é recorte pessoal. Sem acesso completo (ADR 0018) sobra o que é do próprio
        usuário — a meta pessoal — e o resto sai `None`.
        """
        base_currency = workspace_base_currency(db, workspace_id)
        # 1. Current spent (Transactions in the month)
        first_day = date(target_month.year, target_month.month, 1)
        last_day_num = calendar.monthrange(target_month.year, target_month.month)[1]
        last_day = date(target_month.year, target_month.month, last_day_num)
        # Mesma definição de mês do resto do app (ver domain.dates.month_key)
        billing_month = month_key(target_month)

        if not full_access:
            # Saída curta: a projeção da casa inteira não é computada nem em parte.
            # A meta pessoal é a única coisa que o membro restrito tem aqui, e é
            # dela que o Início monta a barra de "sua despesa × seu orçamento".
            my_budget = Decimal("0.00")
            if user_id is not None:
                my_budget = db.exec(
                    select(func.coalesce(func.sum(MonthlyEstimate.amount), 0))
                    .where(MonthlyEstimate.workspace_id == workspace_id)
                    .where(MonthlyEstimate.month == billing_month)
                    .where(MonthlyEstimate.deleted_at.is_(None))
                    .where(MonthlyEstimate.owner_user_id == user_id)
                ).one() or Decimal("0.00")
            return {
                "month": target_month.strftime("%Y-%m"),
                "base_currency": base_currency,
                "my_budget": my_budget,
                "excluded_foreign_count": None,
                "actual_spent": None,
                "projected_eom": None,
                "daily_average": None,
                "remaining_days": None,
                "fixed_costs_pending": None,
                "card_statements_pending": None,
                "total_budget": None,
                "is_over_budget": None,
                "income_actual": None,
                "income_pending": None,
                "projected_income": None,
                "projected_net": None,
            }

        # Gastos em dinheiro do mês. Transações vinculadas a fatura de cartão
        # (statement_id) ficam FORA do fluxo de caixa: o evento de caixa é a
        # fatura no vencimento (evita contagem dupla).
        transactions = db.exec(
            select(Transaction)
            .where(Transaction.workspace_id == workspace_id)
            .where(Transaction.billing_month == billing_month)
            .where(Transaction.deleted_at.is_(None))
            .where(Transaction.statement_id.is_(None))
            .where(Transaction.status.in_(FORECAST_STATUSES))
            .where(Transaction.currency == base_currency)
        ).all()

        total_spent = sum((t.total_amount for t in transactions), Decimal("0.00"))

        # Base da TENDÊNCIA: só gasto variável. Extrapolar por dia um custo que
        # não se repete no mês inflava a projeção de forma grosseira — um aluguel
        # de 3.000 lançado no dia 1, visto no dia 5, virava média de 600/dia e
        # somava ~15.600 de gasto imaginário até o fim do mês. E ele já é contado
        # duas vezes: uma no realizado, outra em `remaining_fixed` (o que ainda
        # vence) ou nas parcelas dos meses seguintes. Errar para MAIS numa
        # previsão de orçamento é o que ensina o usuário a ignorá-la.
        variable_spent = sum(
            (
                t.total_amount for t in transactions
                if t.recurring_expense_id is None and t.installment_group_id is None
            ),
            Decimal("0.00"),
        )

        # Faturas de cartão com vencimento neste mês (ainda não pagas) são caixa a sair.
        # `deleted_at` no filtro: sem ele, a fatura de um cartão EXCLUÍDO seguia
        # sendo somada aqui enquanto o Endividamento (LiabilityService._cards, que
        # filtra) a ignorava — as duas telas mostravam dívidas diferentes para o
        # mesmo mês, sem nada por onde reconciliar. As duas leem o mesmo universo.
        card_statements_due = db.exec(
            select(CardStatement)
            .join(CreditCard, CreditCard.id == CardStatement.card_id)
            # Cartões deste workspace + os compartilhados (ADR 0019)
            .where(cards_of_workspace(workspace_id))
            .where(CreditCard.deleted_at.is_(None))
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
            
        daily_avg = (variable_spent / days_passed).quantize(Decimal("0.01")) if days_passed > 0 else Decimal("0.00")
        
        # 3. Fixed Costs (Remaining Recurring Expenses)
        recurring = db.exec(
            select(RecurringExpense)
            .where(RecurringExpense.workspace_id == workspace_id)
            .where(RecurringExpense.is_active.is_(True))
        ).all()

        # Ocorrências que JÁ têm instância lançada no mês não entram de novo
        # (a instância já está em total_spent) — evita contagem dupla.
        # Semanal deduplica por data exata; mensal/anual por template no mês.
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
        excluded_recurring = 0
        is_current = today.month == target_month.month and today.year == target_month.year
        if is_current or target_month > today:
            for r in recurring:
                for occ in RecurringService.occurrences_in_month(
                    r, target_month.year, target_month.month
                ):
                    if is_current and occ <= today:
                        continue  # vencida: ou já virou instância, ou generate cobre
                    if _occurrence_pending(r, occ):
                        valor, ok = _template_amount_in_base(db, r, occ, base_currency)
                        if ok:
                            remaining_fixed += valor
                        else:
                            excluded_recurring += 1

        # 4. Projected Total (caixa: gastos + tendência + fixos pendentes + faturas a vencer)
        projected_total = total_spent + (daily_avg * remaining_days) + remaining_fixed + statements_pending
        
        # 5. Budget Comparison (Monthly Estimates) — excluídas ficam fora.
        # `total_budget` é a meta da CASA (owner_user_id IS NULL): a previsão é
        # projeção de CAIXA do workspace, não de consumo de uma pessoa — por isso
        # ela continua sendo visão da casa mesmo com o orçamento tendo escopo.
        estimates = db.exec(
            select(MonthlyEstimate)
            .where(MonthlyEstimate.workspace_id == workspace_id)
            .where(MonthlyEstimate.month == billing_month)
            .where(MonthlyEstimate.deleted_at.is_(None))
            .where(MonthlyEstimate.owner_user_id.is_(None))
        ).all()

        total_budget = sum((e.amount for e in estimates), Decimal("0.00"))

        # Meta PESSOAL de quem pediu — é ela que o Início compara com "sua
        # despesa". Sem `user_id` (chamadas internas), fica zerada.
        my_budget = Decimal("0.00")
        if user_id is not None:
            my_budget = db.exec(
                select(func.coalesce(func.sum(MonthlyEstimate.amount), 0))
                .where(MonthlyEstimate.workspace_id == workspace_id)
                .where(MonthlyEstimate.month == billing_month)
                .where(MonthlyEstimate.deleted_at.is_(None))
                .where(MonthlyEstimate.owner_user_id == user_id)
            ).one() or Decimal("0.00")

        # 6. Renda do mês (INC-001): a previsão precisa do outro lado do caixa —
        # sobra projetada = renda recebida no mês − gasto projetado
        income_actual = db.exec(
            select(func.sum(Income.amount))
            .where(income_of_workspace(workspace_id))
            .where(Income.received_at >= datetime.combine(first_day, datetime.min.time()))
            .where(Income.received_at <= datetime.combine(last_day, datetime.max.time()))
            .where(Income.deleted_at.is_(None))
            # Mesma política de moeda da despesa (ADR 0006). Sem este filtro, uma
            # renda legada em USD era somada a despesas em BRL.
            .where(Income.currency == base_currency)
        ).one() or Decimal("0.00")

        # 6b. Rendas recorrentes ainda NÃO materializadas no mês → projeção.
        # Simétrico ao remaining_fixed das despesas: já materializadas contam em
        # income_actual; as pendentes (sem instância) entram como renda esperada.
        income_pending = Decimal("0.00")
        if is_current or target_month > today:
            # Templates da CASA + os PESSOAIS já compartilhados com ela: a
            # previsão é caixa da casa, então salário pessoal só entra depois de o
            # dono compartilhar (ADR 0019).
            recurring_incomes = db.exec(
                select(RecurringIncome)
                .where(
                    or_(
                        RecurringIncome.workspace_id == workspace_id,
                        RecurringIncome.id.in_(
                            select(RecurringIncomeWorkspaceShare.recurring_income_id).where(
                                RecurringIncomeWorkspaceShare.workspace_id == workspace_id
                            )
                        ),
                    )
                )
                .where(RecurringIncome.is_active.is_(True))
            ).all()
            materialized_income = db.exec(
                select(Income.recurring_income_id, Income.received_at)
                .where(income_of_workspace(workspace_id))
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
                        valor, ok = _template_amount_in_base(db, ri, occ, base_currency)
                        if ok:
                            income_pending += valor
                        else:
                            excluded_recurring += 1

        projected_income = income_actual + income_pending

        # Lançamentos em moeda estrangeira ficam fora da projeção (ADR 0006);
        # a contagem sinaliza isso ao usuário (E5/F-04).
        excluded_foreign_count = db.exec(
            select(func.count(Transaction.id))
            .where(Transaction.workspace_id == workspace_id)
            .where(Transaction.billing_month == billing_month)
            .where(Transaction.deleted_at.is_(None))
            .where(Transaction.status.in_(FORECAST_STATUSES))
            .where(Transaction.currency != base_currency)
        ).one() or 0

        return {
            "month": target_month.strftime("%Y-%m"),
            "base_currency": base_currency,
            "excluded_foreign_count": excluded_foreign_count + excluded_recurring,
            "actual_spent": total_spent,
            "projected_eom": projected_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "daily_average": daily_avg,
            "remaining_days": remaining_days,
            "fixed_costs_pending": remaining_fixed,
            "card_statements_pending": statements_pending,
            "total_budget": total_budget,
            "is_over_budget": projected_total > total_budget if total_budget > 0 else False,
            # Meta pessoal de quem pediu (o Início compara com "sua despesa")
            "my_budget": my_budget,
            "income_actual": income_actual,
            "income_pending": income_pending,
            "projected_income": projected_income,
            "projected_net": (projected_income - projected_total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        }
