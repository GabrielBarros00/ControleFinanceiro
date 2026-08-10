from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from typing import Any, Dict, Optional
from sqlmodel import Session, select, func
from app.domain.dates import month_key, today_local
from app.domain.query_policy import (
    FORECAST_STATUSES,
    workspace_base_currency,
)
from app.models.transaction import Transaction
from app.models.recurring import (
    RecurrenceFrequency,
    RecurringExpense,
)
from app.models.estimate import MonthlyEstimate
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

        A previsão projeta o GASTO da casa: o que já saiu no mês, a média diária,
        os fixos a vencer e a comparação com o orçamento. Renda e sobra NÃO estão
        aqui desde o ADR 0021 — são pessoais, e "renda global − gasto de um
        workspace" era o número enganoso que aquele ADR removeu; eles vivem em
        `/me/overview`, que soma tudo.

        Sem acesso completo (ADR 0018) sobra o que é do próprio usuário — a meta
        pessoal — e o resto sai `None`, com as MESMAS chaves: uma rota que muda o
        conjunto de campos conforme o acesso é contrato que diverge sozinho.
        """
        base_currency = workspace_base_currency(db, workspace_id)
        # 1. Current spent (Transactions in the month)
        last_day_num = calendar.monthrange(target_month.year, target_month.month)[1]
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
            # AS MESMAS CHAVES da saída completa, com `None` no que é da casa.
            # Este bloco vinha listando cinco campos que a saída completa não
            # devolve mais: `income_actual`, `income_pending`, `projected_income`
            # e `projected_net` saíram no ADR 0021 (renda não é do workspace), e
            # `card_statements_pending` deixou de ser calculado. O resultado é o
            # tipo de deriva que produz bug de contrato: a MESMA rota respondia
            # com conjuntos de chaves diferentes conforme o acesso de quem
            # perguntava, e quatro delas anunciavam um número que o app não
            # calcula mais em lugar nenhum.
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
                "total_budget": None,
                "is_over_budget": None,
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

        # A fatura de cartão NÃO entra mais aqui (ADR 0021). Cartão é pessoal: a
        # fatura a vencer é caixa a sair DO DONO, não do workspace, e somá-la à
        # projeção da casa colocava a dívida de uma pessoa no orçamento de todas.
        # Esse número agora vive em `/me/commitments`, separado por prazo.

        # 2. Daily Average (Trend-based)
        today = today_local()
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
        #
        # `occurrence_date` (a data canônica da ocorrência) e não
        # `transaction_date.date()`: o instante pode ter sido editado depois, e aí
        # a previsão deixava de reconhecer a instância já lançada e somava a
        # ocorrência DE NOVO por cima dela. Mesma chave que o dedup da
        # materialização usa (`recurring_service.generate_due_instances`).
        instanced = db.exec(
            select(Transaction.recurring_expense_id, Transaction.occurrence_date)
            .where(Transaction.workspace_id == workspace_id)
            .where(Transaction.billing_month == billing_month)
            .where(Transaction.recurring_expense_id.is_not(None))
            .where(Transaction.deleted_at.is_(None))
        ).all()
        instanced_dates = {(rid, occ) for rid, occ in instanced if occ is not None}
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

        # 4. Projected Total (gasto do workspace: realizado + tendência + fixos pendentes)
        projected_total = total_spent + (daily_avg * remaining_days) + remaining_fixed

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

        # 6. Renda NÃO entra na previsão do workspace (ADR 0021).
        #
        # Ela é pessoal, e "renda − gasto do workspace" era exatamente o número
        # enganoso que a auditoria encontrou no Painel: um numerador global menos
        # um denominador local. Quem participa de dois workspaces via o mesmo
        # salário combinado com um subconjunto diferente das despesas em cada um,
        # e as duas "sobras" eram maiores que a real. A previsão da casa projeta
        # GASTO; renda e resultado vivem em `/me/overview`, que soma tudo.

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
            "total_budget": total_budget,
            "is_over_budget": projected_total > total_budget if total_budget > 0 else False,
            # Meta pessoal de quem pediu (o Painel compara com "sua parte")
            "my_budget": my_budget,
        }
