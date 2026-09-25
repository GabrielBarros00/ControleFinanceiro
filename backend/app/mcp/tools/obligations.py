"""O que se deve e o que vem pela frente: dívidas entre pessoas, contas a pagar,
rendas e recorrências. Somente leitura, pelos mesmos serviços das telas."""
from __future__ import annotations

import datetime as dt

from datetime import date
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, Field
from sqlmodel import select

from app.domain.access_policy import personal_scope, shared_or_mine_scope
from app.domain.dates import local_day, month_bounds_utc, parse_month, today_local
from app.domain.income_settlement import income_status
from app.mcp import resolve, versioning
from app.mcp.dates import MonthKey
from app.mcp.errors import ErrorCode, McpToolError
from app.mcp.money import MoneyOut, fmt_brl
from app.mcp.registry import ToolCall, ToolInput, ToolOutput, tool
from app.mcp.schemas import PersonAmount, Ref
from app.mcp.serializers import civil
from app.mcp.tools.reports import _moeda
from app.models.category import Category
from app.models.credit_card import CreditCard
from app.models.income import Income
from app.models.merchant import Merchant
from app.models.payment_account import PaymentAccount
from app.models.recurring import RecurringIncome
from app.models.recurring import RecurringExpense
from app.services.oauth import scopes as escopos
from app.services.overview_service import OverviewService
from app.services.payables_service import PayablesService
from app.services.personal_debt_service import PersonalDebtService
from app.services.recurring_service import RecurringService

_LEITURA = dict(scope=escopos.FINANCE_READ, kind="read", read_only=True, destructive=False, idempotent=True)


def _mes_atual() -> date:
    hoje = today_local()
    return date(hoje.year, hoje.month, 1)


# --- debts_summary ------------------------------------------------------------------

class DebtsIn(ToolInput):
    person: Optional[str] = Field(None, max_length=120, description="Só o saldo com esta pessoa.")
    person_id: Optional[int] = None
    space: Optional[str] = Field(None, max_length=120)
    space_id: Optional[int] = None
    month: Optional[MonthKey] = Field(None, description="Retrato de UM mês (competência). Omitido: saldo acumulado.")
    include_history: bool = Field(False, description="Inclui os últimos acertos registrados.")
    history_limit: int = Field(10, ge=1, le=50)
    currency: Optional[str] = Field(None, min_length=3, max_length=3)


class DebtLine(BaseModel):
    person: Ref
    direction: Literal["owes_you", "you_owe"] = Field(description="owes_you = a pessoa te deve; you_owe = você deve a ela.")
    amount: MoneyOut


class SpaceDebts(BaseModel):
    space: Ref
    currency: str
    balances: List[DebtLine]
    to_pay: MoneyOut
    to_receive: MoneyOut


class SettlementLine(BaseModel):
    id: int
    space: Ref
    counterparty: Ref
    direction: str = Field(description="paid = você pagou; received = você recebeu.")
    amount: MoneyOut
    currency: str
    date: dt.date
    month: Optional[str] = None
    note: Optional[str] = None


class DebtsOut(BaseModel):
    scope: str = Field(description="accumulated (saldo em aberto) | month (retrato do mês)")
    month: Optional[str] = None
    currency: str
    to_pay: MoneyOut = Field(description="Quanto você deve, somado na moeda de relatório.")
    to_receive: MoneyOut = Field(description="Quanto te devem, somado na moeda de relatório.")
    spaces: List[SpaceDebts] = Field(description="Por espaço — saldos de espaços diferentes NUNCA se compensam.")
    history: Optional[List[SettlementLine]] = None


def _linhas(net_debts, me: int, filtro: Optional[int]) -> list[DebtLine]:
    linhas = []
    for d in net_debts:
        dados = d if isinstance(d, dict) else d.model_dump()
        if dados["creditor_id"] == me:
            outro, nome, direcao = dados["debtor_id"], dados.get("debtor_name"), "owes_you"
        elif dados["debtor_id"] == me:
            outro, nome, direcao = dados["creditor_id"], dados.get("creditor_name"), "you_owe"
        else:
            continue
        if filtro is not None and outro != filtro:
            continue
        linhas.append(DebtLine(person=Ref(id=outro, name=nome or f"Pessoa {outro}"), direction=direcao, amount=dados["amount"]))
    return linhas


@tool(
    name="debts_summary",
    title="Quem deve a quem",
    description=(
        "Mostra quanto você deve e quanto te devem, por pessoa e por espaço (saldos de espaços "
        "diferentes não se compensam). Opcionalmente o retrato de um mês e o histórico de acertos.\n"
        "Use quando: 'quanto o João está me devendo?', 'quanto eu devo pra Ana?', 'já acertei com "
        "o Pedro?'.\n"
        "Não use quando: quiser registrar um pagamento entre pessoas (settlements_create)."
    ),
    input_model=DebtsIn,
    output_model=DebtsOut,
    cost=2,
    **_LEITURA,
    app_callable=True,
)
def debts_summary(call: ToolCall) -> ToolOutput:
    a: DebtsIn = call.args
    me = call.identity.user_id
    alvo = resolve.resolve_space(call.session, me, space_id=a.space_id, space=a.space)
    espacos = [alvo] if alvo else resolve.user_spaces(call.session, me)
    pessoa = resolve.person_any(call.session, espacos, me, person_id=a.person_id, person=a.person)
    filtro_espaco = {alvo.id} if alvo else None

    geral = PersonalDebtService.get_personal_debts(call.session, me, currency=_moeda(a.currency))
    grupos: list[SpaceDebts] = []
    if a.month:
        mensal = PersonalDebtService.get_personal_monthly(call.session, me, a.month)
        nomes = {}
        for ref in espacos:
            for m in resolve.space_members(call.session, ref.id):
                nomes[m.id] = m.name
        for g in mensal["by_workspace"]:
            if filtro_espaco and g["workspace_id"] not in filtro_espaco:
                continue
            linhas_brutas = []
            for d in g["net_debts"]:
                dados = d if isinstance(d, dict) else d.model_dump()
                linhas_brutas.append({
                    **dados,
                    "debtor_name": nomes.get(dados["debtor_id"]),
                    "creditor_name": nomes.get(dados["creditor_id"]),
                })
            linhas = _linhas(linhas_brutas, me, pessoa)
            grupos.append(SpaceDebts(
                space=Ref(id=g["workspace_id"], name=g["workspace_name"]),
                currency=g["base_currency"],
                balances=linhas,
                to_pay=sum((x.amount for x in linhas if x.direction == "you_owe"), Decimal("0")),
                to_receive=sum((x.amount for x in linhas if x.direction == "owes_you"), Decimal("0")),
            ))
    else:
        for g in geral["by_workspace"]:
            if filtro_espaco and g["workspace_id"] not in filtro_espaco:
                continue
            linhas = _linhas(g["net_debts"], me, pessoa)
            grupos.append(SpaceDebts(
                space=Ref(id=g["workspace_id"], name=g["workspace_name"]),
                currency=g["base_currency"],
                balances=linhas,
                to_pay=sum((x.amount for x in linhas if x.direction == "you_owe"), Decimal("0")) if pessoa else g["to_pay"],
                to_receive=sum((x.amount for x in linhas if x.direction == "owes_you"), Decimal("0")) if pessoa else g["to_receive"],
            ))

    historico = None
    if a.include_history:
        lista = PersonalDebtService.list_personal_settlements(call.session, me, limit=a.history_limit, offset=0)
        historico = [
            SettlementLine(
                id=e["id"],
                space=Ref(id=e["workspace_id"], name=e["workspace_name"]),
                counterparty=Ref(id=e["counterparty_id"], name=e["counterparty_name"]),
                direction=e["direction"],
                amount=e["amount"],
                currency=e["currency"],
                date=local_day(e["settled_at"]),
                month=e.get("billing_month"),
                note=e.get("note"),
            )
            for e in lista["items"]
            if (pessoa is None or e["counterparty_id"] == pessoa)
            and (filtro_espaco is None or e["workspace_id"] in filtro_espaco)
        ]

    saida = DebtsOut(
        scope="month" if a.month else "accumulated",
        month=a.month,
        currency=geral["currency"],
        to_pay=geral["to_pay"] if not (pessoa or alvo or a.month) else sum((g.to_pay for g in grupos if g.currency == geral["currency"]), Decimal("0")),
        to_receive=geral["to_receive"] if not (pessoa or alvo or a.month) else sum((g.to_receive for g in grupos if g.currency == geral["currency"]), Decimal("0")),
        spaces=grupos,
        history=historico,
    )
    partes = []
    for g in grupos:
        for x in g.balances:
            partes.append(
                f"{x.person.name} te deve {fmt_brl(x.amount, g.currency)} ({g.space.name})"
                if x.direction == "owes_you"
                else f"você deve {fmt_brl(x.amount, g.currency)} a {x.person.name} ({g.space.name})"
            )
    return ToolOutput(structured=saida, summary=("; ".join(partes) or "Nenhum saldo em aberto.") + ".")


# --- payables_list ------------------------------------------------------------------

class PayablesIn(ToolInput):
    month: Optional[MonthKey] = Field(None, description="Mês (YYYY-MM). Omitido: o mês atual.")
    space: Optional[str] = Field(None, max_length=120)
    space_id: Optional[int] = None
    include_overdue: bool = Field(True, description="Inclui o que venceu em meses anteriores e segue em aberto.")


class BillOut(BaseModel):
    transaction_id: int
    space: Ref
    title: str
    due_date: dt.date
    amount: MoneyOut
    currency: str
    overdue: bool
    installment: Optional[str] = None


class CardBillOut(BaseModel):
    card: Ref
    statement_id: int
    month: str
    due_date: dt.date
    amount: MoneyOut
    overdue: bool


class FinancingOut(BaseModel):
    financing_id: int
    title: str
    next_due_date: Optional[dt.date] = None
    next_amount: Optional[MoneyOut] = None
    outstanding: MoneyOut
    remaining_installments: int
    overdue_count: int


class PayablesOut(BaseModel):
    month: str
    currency: str
    bills_total: MoneyOut = Field(description="Contas do mês fora do cartão ainda não pagas.")
    overdue_total: MoneyOut
    bills: List[BillOut]
    card_bills: List[CardBillOut] = Field(description="Faturas de cartão a pagar.")
    financings: List[FinancingOut]


@tool(
    name="payables_list",
    title="Contas a pagar",
    description=(
        "Lista o que você ainda tem a pagar: contas do mês fora do cartão (boletos, Pix agendado, "
        "recorrências), faturas de cartão e parcelas de financiamento, com vencimento e atrasos.\n"
        "Use quando: 'o que tenho pra pagar este mês?', 'tem conta atrasada?', 'quando vence a "
        "fatura?'.\n"
        "Não use quando: quiser marcar algo como pago (transactions_update com paid=true, ou "
        "statements_pay para fatura)."
    ),
    input_model=PayablesIn,
    output_model=PayablesOut,
    cost=2,
    **_LEITURA,
    app_callable=True,
)
def payables_list(call: ToolCall) -> ToolOutput:
    a: PayablesIn = call.args
    me = call.identity.user_id
    mes = parse_month(a.month) if a.month else _mes_atual()
    alvo = resolve.resolve_space(call.session, me, space_id=a.space_id, space=a.space)
    moeda = OverviewService.report_currency(call.session, me)
    contas = PayablesService.list_payables(
        call.session, me, mes, moeda, workspace_id=alvo.id if alvo else None, incluir_atrasadas=a.include_overdue,
    )
    compromissos = OverviewService.get_commitments(call.session, me, currency=moeda)
    saida = PayablesOut(
        month=contas["month"],
        currency=contas["currency"],
        bills_total=contas["total"],
        overdue_total=contas["overdue_total"],
        bills=[
            BillOut(
                transaction_id=e["transaction_id"],
                space=Ref(id=e["workspace_id"], name=e["workspace_name"]),
                title=e["title"],
                due_date=e["due_date"],
                amount=e["amount"],
                currency=e["currency"],
                overdue=e["is_overdue"],
                installment=f"{e['installment_no']}/{e['installments_of']}" if e.get("installment_no") else None,
            )
            for e in contas["entries"]
        ],
        card_bills=[
            CardBillOut(
                card=Ref(id=c["card_id"], name=c["card_name"]),
                statement_id=c["statement_id"],
                month=c["month"],
                due_date=civil(c["due_date"]),
                amount=c["amount"],
                overdue=c["is_overdue"],
            )
            for c in compromissos["cards"]
        ],
        financings=[
            FinancingOut(
                financing_id=f["financing_id"],
                title=f["title"],
                next_due_date=f.get("next_due_date"),
                next_amount=f.get("next_amount"),
                outstanding=f["outstanding"],
                remaining_installments=f["remaining_installments"],
                overdue_count=f.get("overdue_count", 0),
            )
            for f in compromissos["financings"]
        ],
    )
    resumo = (
        f"{len(saida.bills)} conta(s) a pagar ({fmt_brl(saida.bills_total, saida.currency)}), "
        f"{len(saida.card_bills)} fatura(s) e {len(saida.financings)} financiamento(s)."
    )
    return ToolOutput(structured=saida, summary=resumo)


# --- income_list --------------------------------------------------------------------

class IncomeIn(ToolInput):
    month: Optional[MonthKey] = Field(None, description="Competência (YYYY-MM). Omitido: o mês atual.")
    status: Optional[Literal["expected", "received", "overdue", "cancelled"]] = None
    income_id: Optional[int] = Field(None, ge=1, description="Uma renda específica, de qualquer mês.")


class IncomeOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    amount: MoneyOut
    currency: str
    date: dt.date = Field(description="Data prevista/competência.")
    received_on: Optional[dt.date] = None
    status: str = Field(description="expected | received | overdue | cancelled")
    category: Optional[str] = None
    account: Optional[Ref] = Field(None, description="Conta onde caiu (ou vai cair).")
    account_id: Optional[int] = None
    recurring: bool
    recurring_id: Optional[int] = Field(None, description="A renda recorrente que a gerou (recurring_get kind=income).")
    original_amount: Optional[MoneyOut] = Field(None, description="Valor na moeda original, quando estrangeira.")
    original_currency: Optional[str] = None
    version: str = Field("", description="Versão do estado; mande em `expected_version` ao editar.")


def income_out(r: Income, contas: Optional[dict[int, str]] = None) -> IncomeOut:
    saida = IncomeOut(
        id=r.id, title=r.title, description=r.description, amount=r.amount, currency=r.currency,
        date=local_day(r.received_at),
        received_on=local_day(r.settled_at) if r.settled_at else None,
        status=income_status(settled_at=r.settled_at, cancelled_at=r.cancelled_at, received_at=r.received_at),
        category=r.category,
        account=Ref(id=r.account_id, name=(contas or {}).get(r.account_id, "?")) if r.account_id else None,
        account_id=r.account_id,
        recurring=r.recurring_income_id is not None,
        recurring_id=r.recurring_income_id,
        original_amount=r.original_amount, original_currency=r.original_currency,
    )
    saida.version = versioning.version_of(saida)
    return saida


def nomes_de_contas(call: ToolCall, ids) -> dict[int, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict(call.session.exec(
        select(PaymentAccount.id, PaymentAccount.name).where(
            PaymentAccount.id.in_(ids), PaymentAccount.owner_user_id == call.identity.user_id,
        )
    ).all())


class IncomeListOut(BaseModel):
    month: Optional[str] = None
    currency_totals: dict[str, MoneyOut] = Field(description="Total por moeda, sem as canceladas.")
    incomes: List[IncomeOut]


@tool(
    name="income_list",
    title="Rendas do mês",
    description=(
        "Lista suas rendas (salário, freelas, reembolsos) do mês, com situação: prevista, "
        "recebida, atrasada ou cancelada, a conta e a recorrência de origem. Com `income_id`, "
        "devolve só aquela renda (de qualquer mês).\n"
        "Use quando: 'meu salário caiu?', 'quanto vou receber este mês?', ou antes de editar uma renda.\n"
        "Não use quando: quiser registrar ou marcar renda como recebida (income_create / income_update)."
    ),
    input_model=IncomeIn,
    output_model=IncomeListOut,
    **_LEITURA,
    app_callable=True,
)
def income_list(call: ToolCall) -> ToolOutput:
    a: IncomeIn = call.args
    me = call.identity.user_id
    consulta = select(Income).where(Income.deleted_at.is_(None), personal_scope(Income.user_id, me))
    mes = None
    if a.income_id is not None:
        consulta = consulta.where(Income.id == a.income_id)
    else:
        ref = parse_month(a.month) if a.month else _mes_atual()
        mes = ref.strftime("%Y-%m")
        inicio, fim = month_bounds_utc(ref)
        consulta = consulta.where(Income.received_at >= inicio, Income.received_at < fim)
    linhas = call.session.exec(consulta.order_by(Income.received_at, Income.id)).all()
    if a.income_id is not None and not linhas:
        raise McpToolError(ErrorCode.NOT_FOUND, "Renda não encontrada.", details={"income_id": a.income_id})
    contas = nomes_de_contas(call, (r.account_id for r in linhas))
    rendas: list[IncomeOut] = []
    totais: dict[str, Decimal] = {}
    for r in linhas:
        item = income_out(r, contas)
        if a.status and item.status != a.status:
            continue
        if item.status != "cancelled":
            totais[r.currency] = totais.get(r.currency, Decimal("0")) + Decimal(r.amount)
        rendas.append(item)
    return ToolOutput(
        structured=IncomeListOut(month=mes, currency_totals=totais, incomes=rendas),
        summary=f"{len(rendas)} renda(s)" + (f" em {mes}." if mes else "."),
        entity_type="income",
        entity_ids=[r.id for r in rendas],
    )


# --- recurring_list / recurring_get ------------------------------------------------

class RecurringIn(ToolInput):
    space: Optional[str] = Field(None, max_length=120)
    space_id: Optional[int] = None
    kind: Literal["all", "expense", "income"] = "all"
    active_only: bool = True
    subscriptions_only: bool = Field(False, description="Só assinaturas.")


class SubscriptionOut(BaseModel):
    plan: Optional[str] = None
    trial_ends_on: Optional[dt.date] = Field(None, description="Fim do teste grátis.")
    notes: Optional[str] = Field(None, description="Benefícios/observações.")


class RecurringOut(BaseModel):
    id: int
    kind: str = Field(description="expense | income")
    space: Optional[Ref] = Field(None, description="Espaço (só despesas; renda é pessoal).")
    title: str
    description: Optional[str] = None
    amount: MoneyOut = Field(description="Valor de cada ocorrência (cheio).")
    currency: str
    my_share: MoneyOut = Field(description="A SUA parte em cada ocorrência.")
    split: List[PersonAmount] = Field(default_factory=list, description="Quem deve quanto em cada ocorrência.")
    paid_by: Optional[Ref] = None
    frequency: str
    interval: int
    day_of_month: Optional[int] = None
    active: bool
    start_date: Optional[dt.date] = None
    end_date: Optional[dt.date] = None
    next_occurrence: Optional[dt.date] = None
    occurrences_remaining: Optional[int] = None
    payment_method: Optional[str] = None
    card: Optional[Ref] = None
    account: Optional[Ref] = None
    category: Optional[Ref] = None
    auto_settle: Optional[bool] = Field(None, description="Despesa: marca como paga sozinha na data. Renda: confirma sozinha.")
    card_id: Optional[int] = None
    category_id: Optional[int] = None
    merchant: Optional[Ref] = Field(None, description="Estabelecimento (o provedor, numa assinatura).")
    subscription: Optional[SubscriptionOut] = Field(None, description="Presente quando é assinatura (ADR 0039).")
    my_monthly: Optional[MoneyOut] = Field(None, description="A SUA parte por mês (anual ÷ 12, semanal × 52 ÷ 12).")
    version: str = Field("", description="Versão do estado; mande em `expected_version` ao editar.")


def _proximas(template, hoje: date, quantas: int = 1) -> list[date]:
    return RecurringService.next_occurrences(template, hoje, quantas)


def _divisao_da_recorrencia(t: RecurringExpense, nomes: dict[int, str], me: int) -> tuple[list[PersonAmount], Decimal, Optional[int]]:
    """A divisão de CADA ocorrência, pelo mesmo cálculo que a gera (snapshot → SplitService)."""
    pagador, _ = RecurringService._participants(t)
    pessoas = [
        PersonAmount(person=Ref(id=uid, name=nomes.get(uid, f"Pessoa {uid}")), amount=valor, is_me=uid == me)
        for uid, valor in RecurringService.shares_per_occurrence(t)
    ]
    minha = sum((p.amount for p in pessoas if p.is_me), Decimal("0.00"))
    return pessoas, minha, pagador


def recurring_expense_out(
    call: ToolCall, t: RecurringExpense, espaco: Ref, hoje: date, nomes: Optional[dict[int, str]] = None,
) -> RecurringOut:
    me = call.identity.user_id
    if nomes is None:
        nomes = {m.id: m.name for m in resolve.space_members(call.session, t.workspace_id)}
    total = RecurringService.count_occurrences(t)
    restantes = None if total is None else max(0, total - (RecurringService.count_occurrences(t, ate=hoje) or 0))
    pessoas, minha, pagador = _divisao_da_recorrencia(t, nomes, me)
    cartao = call.session.get(CreditCard, t.credit_card_id) if t.credit_card_id else None
    conta = call.session.get(PaymentAccount, t.account_id) if t.account_id else None
    categoria = call.session.get(Category, t.category_id) if t.category_id else None
    estabelecimento = call.session.get(Merchant, t.merchant_id) if t.merchant_id else None
    proxima = _proximas(t, hoje) if t.is_active else []
    saida = RecurringOut(
        id=t.id, kind="expense", space=espaco,
        title=t.title, description=t.description, amount=t.base_amount, currency=t.currency,
        my_share=minha, split=pessoas,
        paid_by=Ref(id=pagador, name=nomes.get(pagador, "?")) if pagador else None,
        frequency=getattr(t.frequency, "value", t.frequency), interval=t.interval,
        day_of_month=t.day_of_month, active=t.is_active, start_date=t.start_date,
        end_date=t.end_date, next_occurrence=proxima[0] if proxima else None,
        occurrences_remaining=restantes,
        payment_method=getattr(t.payment_method, "value", t.payment_method) if t.payment_method else None,
        card=Ref(id=cartao.id, name=cartao.name) if cartao and cartao.owner_user_id == me else None,
        # Conta é de uma pessoa: o nome só sai para o dono dela.
        account=Ref(id=conta.id, name=conta.name) if conta and conta.owner_user_id == me else None,
        category=Ref(id=categoria.id, name=categoria.name) if categoria else None,
        auto_settle=t.auto_settle,
        card_id=t.credit_card_id, category_id=t.category_id,
        merchant=Ref(id=estabelecimento.id, name=estabelecimento.name)
        if estabelecimento and estabelecimento.deleted_at is None else None,
        subscription=SubscriptionOut(plan=t.plan, trial_ends_on=t.trial_ends_on, notes=t.notes) if t.is_subscription else None,
        my_monthly=RecurringService.monthly_equivalent(minha, t.frequency, t.interval),
    )
    saida.version = versioning.version_of(saida, ignore=("next_occurrence", "occurrences_remaining"))
    return saida


def recurring_income_out(call: ToolCall, r: RecurringIncome, hoje: date) -> RecurringOut:
    me = call.identity.user_id
    conta = call.session.get(PaymentAccount, r.account_id) if r.account_id else None
    proxima = _proximas(r, hoje) if r.is_active else []
    total = RecurringService.count_occurrences(r)
    restantes = None if total is None else max(0, total - (RecurringService.count_occurrences(r, ate=hoje) or 0))
    eu = Ref(id=me, name=call.user.name)
    saida = RecurringOut(
        id=r.id, kind="income", title=r.title, description=r.description,
        amount=r.base_amount, currency=r.currency,
        my_share=r.base_amount, split=[PersonAmount(person=eu, amount=r.base_amount, is_me=True)], paid_by=None,
        frequency=getattr(r.frequency, "value", r.frequency), interval=r.interval,
        day_of_month=r.day_of_month, active=r.is_active, start_date=r.start_date, end_date=r.end_date,
        next_occurrence=proxima[0] if proxima else None, occurrences_remaining=restantes,
        account=Ref(id=conta.id, name=conta.name) if conta else None,
        category=None, auto_settle=r.auto_confirm,
    )
    saida.version = versioning.version_of(saida, ignore=("next_occurrence", "occurrences_remaining"))
    return saida


class RecurringListOut(BaseModel):
    items: List[RecurringOut]
    monthly_my_share: dict[str, MoneyOut] = Field(
        default_factory=dict,
        description="Despesas ativas: soma da SUA parte por mês (anual ÷ 12, semanal × 52 ÷ 12), por moeda.",
    )


def por_mes(item: RecurringOut) -> Decimal:
    """A SUA parte por mês (a mesma conta da tela de recorrências, ADR 0039)."""
    return RecurringService.monthly_equivalent(Decimal(item.my_share), item.frequency, item.interval)


@tool(
    name="recurring_list",
    title="Despesas e rendas recorrentes",
    description=(
        "Lista suas despesas recorrentes (aluguel, assinaturas, contas fixas) por espaço e suas "
        "rendas recorrentes (salário): valor cheio, a SUA parte, divisão, quem paga, cartão/conta, "
        "próxima ocorrência e se ainda estão ativas. Assinaturas (`subscriptions_only`) com plano, "
        "teste grátis e o custo por mês.\n"
        "Use quando: 'quais são minhas assinaturas?', 'quanto pago de contas fixas?', ou antes de "
        "editar uma recorrência (recurring_update precisa do id).\n"
        "Não use quando: quiser os lançamentos já gerados (transactions_search)."
    ),
    input_model=RecurringIn,
    output_model=RecurringListOut,
    **_LEITURA,
    app_callable=True,
)
def recurring_list(call: ToolCall) -> ToolOutput:
    a: RecurringIn = call.args
    me = call.identity.user_id
    alvo = resolve.resolve_space(call.session, me, space_id=a.space_id, space=a.space)
    itens: list[RecurringOut] = []
    hoje = today_local()
    if a.kind in ("all", "expense"):
        espacos = [alvo] if alvo else resolve.user_spaces(call.session, me)
        for ref in espacos:
            consulta = select(RecurringExpense).where(
                RecurringExpense.workspace_id == ref.id,
                shared_or_mine_scope(RecurringExpense.created_by_user_id, ref.membership),
            )
            if a.active_only:
                consulta = consulta.where(RecurringExpense.is_active.is_(True))
            if a.subscriptions_only:
                consulta = consulta.where(RecurringExpense.is_subscription.is_(True))
            nomes = {m.id: m.name for m in resolve.space_members(call.session, ref.id)}
            for t in call.session.exec(consulta.order_by(RecurringExpense.title)).all():
                itens.append(recurring_expense_out(call, t, Ref(id=ref.id, name=ref.workspace.name), hoje, nomes))
    if a.kind in ("all", "income") and alvo is None and not a.subscriptions_only:
        consulta = select(RecurringIncome).where(personal_scope(RecurringIncome.user_id, me))
        if a.active_only:
            consulta = consulta.where(RecurringIncome.is_active.is_(True))
        for r in call.session.exec(consulta.order_by(RecurringIncome.title)).all():
            itens.append(recurring_income_out(call, r, hoje))
    mensal: dict[str, Decimal] = {}
    for i in itens:
        if i.kind == "expense" and i.active:
            mensal[i.currency] = mensal.get(i.currency, Decimal("0.00")) + por_mes(i)
    return ToolOutput(
        structured=RecurringListOut(items=itens, monthly_my_share=mensal),
        summary=f"{len(itens)} recorrência(s)."
        + (" Sua parte por mês nas despesas: " + ", ".join(fmt_brl(v, k) for k, v in mensal.items()) + "." if mensal else ""),
        entity_type="recurring",
        entity_ids=[i.id for i in itens],
    )


class RecurringGetIn(ToolInput):
    recurring_id: int = Field(ge=1)
    kind: Literal["expense", "income"] = Field("expense", description="expense = despesa recorrente; income = renda recorrente.")


class RecurringDetailOut(BaseModel):
    recurring: RecurringOut
    upcoming: List[dt.date] = Field(description="As próximas ocorrências (até 6).")


def visible_recurring(call: ToolCall, recurring_id: int) -> tuple[RecurringExpense, "resolve.SpaceRef"]:
    """A despesa recorrente, se ESTA pessoa pode vê-la (mesmo recorte da lista); senão NOT_FOUND."""
    t = call.session.get(RecurringExpense, recurring_id)
    if t is not None:
        for ref in resolve.user_spaces(call.session, call.identity.user_id):
            if ref.id == t.workspace_id:
                visivel = call.session.exec(
                    select(RecurringExpense.id).where(
                        RecurringExpense.id == t.id,
                        shared_or_mine_scope(RecurringExpense.created_by_user_id, ref.membership),
                    )
                ).first()
                if visivel is not None:
                    return t, ref
    raise McpToolError(ErrorCode.NOT_FOUND, "Recorrência não encontrada.", details={"recurring_id": recurring_id})


def own_recurring_income(call: ToolCall, recurring_id: int) -> RecurringIncome:
    r = call.session.get(RecurringIncome, recurring_id)
    if r is None or r.user_id != call.identity.user_id:
        raise McpToolError(ErrorCode.NOT_FOUND, "Renda recorrente não encontrada.", details={"recurring_id": recurring_id})
    return r


@tool(
    name="recurring_get",
    title="Ver recorrência",
    description=(
        "Devolve UMA recorrência completa pelo id: valor, a sua parte, a divisão de cada ocorrência, "
        "quem paga, forma de pagamento, cartão/conta, categoria, início/fim e as próximas datas.\n"
        "Use quando: precisar do estado inteiro antes de editar (recurring_update) ou para explicar "
        "quanto uma assinatura dividida custa para o usuário.\n"
        "Não use quando: quiser a lista (recurring_list)."
    ),
    input_model=RecurringGetIn,
    output_model=RecurringDetailOut,
    **_LEITURA,
    app_callable=True,
)
def recurring_get(call: ToolCall) -> ToolOutput:
    a: RecurringGetIn = call.args
    hoje = today_local()
    if a.kind == "income":
        r = own_recurring_income(call, a.recurring_id)
        saida = recurring_income_out(call, r, hoje)
        proximas = _proximas(r, hoje, 6) if r.is_active else []
        espaco_id = None
    else:
        t, ref = visible_recurring(call, a.recurring_id)
        saida = recurring_expense_out(call, t, Ref(id=ref.id, name=ref.workspace.name), hoje)
        proximas = _proximas(t, hoje, 6) if t.is_active else []
        espaco_id = ref.id
    return ToolOutput(
        structured=RecurringDetailOut(recurring=saida, upcoming=proximas),
        summary=f"{saida.title}: {fmt_brl(saida.amount, saida.currency)} ({saida.frequency}); "
        f"sua parte {fmt_brl(saida.my_share, saida.currency)}"
        + (f"; próxima em {proximas[0].strftime('%d/%m/%Y')}." if proximas else "."),
        entity_type="recurring",
        entity_ids=[saida.id],
        space_id=espaco_id,
    )
