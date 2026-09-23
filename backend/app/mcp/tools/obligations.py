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
from app.mcp import resolve
from app.mcp.dates import MonthKey
from app.mcp.money import MoneyOut, fmt_brl
from app.mcp.registry import ToolCall, ToolInput, ToolOutput, tool
from app.mcp.schemas import Ref
from app.mcp.serializers import civil
from app.mcp.tools.reports import _moeda
from app.models.income import Income
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


class IncomeOut(BaseModel):
    id: int
    title: str
    amount: MoneyOut
    currency: str
    date: dt.date = Field(description="Data prevista/competência.")
    received_on: Optional[dt.date] = None
    status: str = Field(description="expected | received | overdue | cancelled")
    category: Optional[str] = None
    account_id: Optional[int] = None
    recurring: bool
    original_amount: Optional[MoneyOut] = Field(None, description="Valor na moeda original, quando estrangeira.")
    original_currency: Optional[str] = None


def income_out(r: Income) -> IncomeOut:
    return IncomeOut(
        id=r.id, title=r.title, amount=r.amount, currency=r.currency,
        date=local_day(r.received_at),
        received_on=local_day(r.settled_at) if r.settled_at else None,
        status=income_status(settled_at=r.settled_at, cancelled_at=r.cancelled_at, received_at=r.received_at),
        category=r.category, account_id=r.account_id,
        recurring=r.recurring_income_id is not None,
        original_amount=r.original_amount, original_currency=r.original_currency,
    )


class IncomeListOut(BaseModel):
    month: str
    currency_totals: dict[str, MoneyOut] = Field(description="Total por moeda, sem as canceladas.")
    incomes: List[IncomeOut]


@tool(
    name="income_list",
    title="Rendas do mês",
    description=(
        "Lista suas rendas (salário, freelas, reembolsos) do mês, com situação: prevista, "
        "recebida, atrasada ou cancelada.\n"
        "Use quando: 'meu salário caiu?', 'quanto vou receber este mês?'.\n"
        "Não use quando: quiser registrar ou marcar renda como recebida (income_create / income_update)."
    ),
    input_model=IncomeIn,
    output_model=IncomeListOut,
    **_LEITURA,
)
def income_list(call: ToolCall) -> ToolOutput:
    a: IncomeIn = call.args
    me = call.identity.user_id
    ref = parse_month(a.month) if a.month else _mes_atual()
    inicio, fim = month_bounds_utc(ref)
    linhas = call.session.exec(
        select(Income).where(
            Income.deleted_at.is_(None),
            personal_scope(Income.user_id, me),
            Income.received_at >= inicio,
            Income.received_at < fim,
        ).order_by(Income.received_at, Income.id)
    ).all()
    rendas: list[IncomeOut] = []
    totais: dict[str, Decimal] = {}
    for r in linhas:
        item = income_out(r)
        if a.status and item.status != a.status:
            continue
        if item.status != "cancelled":
            totais[r.currency] = totais.get(r.currency, Decimal("0")) + Decimal(r.amount)
        rendas.append(item)
    return ToolOutput(
        structured=IncomeListOut(month=ref.strftime("%Y-%m"), currency_totals=totais, incomes=rendas),
        summary=f"{len(rendas)} renda(s) em {ref.strftime('%Y-%m')}.",
        entity_type="income",
        entity_ids=[r.id for r in rendas],
    )


# --- recurring_list -----------------------------------------------------------------

class RecurringIn(ToolInput):
    space: Optional[str] = Field(None, max_length=120)
    space_id: Optional[int] = None
    kind: Literal["all", "expense", "income"] = "all"
    active_only: bool = True


class RecurringOut(BaseModel):
    id: int
    kind: str = Field(description="expense | income")
    space: Optional[Ref] = Field(None, description="Espaço (só despesas; renda é pessoal).")
    title: str
    amount: MoneyOut
    currency: str
    frequency: str
    interval: int
    day_of_month: Optional[int] = None
    active: bool
    start_date: Optional[dt.date] = None
    end_date: Optional[dt.date] = None
    occurrences_remaining: Optional[int] = None
    card_id: Optional[int] = None
    category_id: Optional[int] = None


def recurring_expense_out(t: RecurringExpense, espaco: Ref, hoje: date) -> RecurringOut:
    total = RecurringService.count_occurrences(t)
    restantes = None if total is None else max(0, total - (RecurringService.count_occurrences(t, ate=hoje) or 0))
    return RecurringOut(
        id=t.id, kind="expense", space=espaco,
        title=t.title, amount=t.base_amount, currency=t.currency,
        frequency=getattr(t.frequency, "value", t.frequency), interval=t.interval,
        day_of_month=t.day_of_month, active=t.is_active, start_date=t.start_date,
        end_date=t.end_date, occurrences_remaining=restantes,
        card_id=t.credit_card_id, category_id=t.category_id,
    )


class RecurringListOut(BaseModel):
    items: List[RecurringOut]


@tool(
    name="recurring_list",
    title="Despesas e rendas recorrentes",
    description=(
        "Lista suas despesas recorrentes (aluguel, assinaturas, contas fixas) por espaço e suas "
        "rendas recorrentes (salário), com valor, frequência e se ainda estão ativas.\n"
        "Use quando: 'quais são minhas assinaturas?', 'quanto pago de contas fixas?', ou antes de "
        "editar uma recorrência (recurring_update precisa do id).\n"
        "Não use quando: quiser os lançamentos já gerados (transactions_search)."
    ),
    input_model=RecurringIn,
    output_model=RecurringListOut,
    **_LEITURA,
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
            for t in call.session.exec(consulta.order_by(RecurringExpense.title)).all():
                itens.append(recurring_expense_out(t, Ref(id=ref.id, name=ref.workspace.name), hoje))
    if a.kind in ("all", "income") and alvo is None:
        consulta = select(RecurringIncome).where(personal_scope(RecurringIncome.user_id, me))
        if a.active_only:
            consulta = consulta.where(RecurringIncome.is_active.is_(True))
        for r in call.session.exec(consulta.order_by(RecurringIncome.title)).all():
            itens.append(RecurringOut(
                id=r.id, kind="income", title=r.title, amount=r.base_amount, currency=r.currency,
                frequency=getattr(r.frequency, "value", r.frequency), interval=r.interval,
                day_of_month=r.day_of_month, active=r.is_active, start_date=r.start_date, end_date=r.end_date,
            ))
    return ToolOutput(
        structured=RecurringListOut(items=itens),
        summary=f"{len(itens)} recorrência(s).",
        entity_type="recurring",
        entity_ids=[i.id for i in itens],
    )

