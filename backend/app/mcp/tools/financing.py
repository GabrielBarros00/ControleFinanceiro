"""Financiamento: ler o contrato inteiro e pagar/desfazer uma parcela.

Cadastrar, editar ou excluir o contrato continua no app (decisão do dono): o
cronograma SAC/PRICE nasce de parâmetros que a pessoa confere na tela. O que o
agente faz é o dia a dia — "quanto falta?", "paguei a parcela deste mês", "marquei
a errada" — pelos mesmos comandos da tela (`services/commands/financing.py`),
com a mesma reivindicação atômica da parcela.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import List, Literal, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlmodel import select

from app.domain.access_policy import personal_scope
from app.domain.dates import civil_instant, local_day, today_local
from app.mcp import resolve
from app.mcp.dates import CivilDate
from app.mcp.errors import ErrorCode, McpToolError
from app.mcp.money import MoneyOut, fmt_brl
from app.mcp.registry import ToolCall, ToolInput, ToolOutput, tool
from app.mcp.schemas import Ref
from app.mcp.serializers import app_url
from app.models.financing import AmortizationInstallment, Financing
from app.models.payment_account import PaymentAccount
from app.schemas.financing import InstallmentPayRequest
from app.services import transaction_query
from app.services.commands import financing as fin_cmd
from app.services.oauth import scopes as escopos


class InstallmentOut(BaseModel):
    number: int
    due_date: dt.date
    principal: MoneyOut
    interest: MoneyOut
    total: MoneyOut
    remaining_balance: MoneyOut = Field(description="Saldo devedor depois desta parcela (pelo cronograma).")
    paid: bool
    paid_on: Optional[dt.date] = None
    account: Optional[Ref] = None
    overdue: bool = False


class FinancingOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    status: str = Field(description="active | settled | simulated")
    method: str = Field(description="SAC | PRICE")
    currency: str
    amount: MoneyOut = Field(description="Valor financiado.")
    monthly_rate: str = Field(description="Taxa de juros MENSAL em fração decimal (\"0.0100\" = 1% a.m.).")
    start_date: dt.date
    installments: int
    paid_installments: int
    remaining_installments: int
    outstanding: MoneyOut = Field(description="Saldo devedor: principal das parcelas em aberto.")
    next_due_date: Optional[dt.date] = None
    next_amount: Optional[MoneyOut] = None
    overdue_count: int
    app_url: str


def _nomes_contas(call: ToolCall, ids) -> dict[int, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict(call.session.exec(
        select(PaymentAccount.id, PaymentAccount.name).where(
            PaymentAccount.id.in_(ids), PaymentAccount.owner_user_id == call.identity.user_id,
        )
    ).all())


def _parcelas(call: ToolCall, f: Financing) -> list[AmortizationInstallment]:
    return list(call.session.exec(
        select(AmortizationInstallment)
        .where(AmortizationInstallment.financing_id == f.id)
        .order_by(AmortizationInstallment.installment_number)
    ).all())


def financing_out(call: ToolCall, f: Financing, parcelas: Optional[list[AmortizationInstallment]] = None) -> FinancingOut:
    parcelas = parcelas if parcelas is not None else _parcelas(call, f)
    hoje = today_local()
    abertas = [p for p in parcelas if not p.is_paid]
    proxima = abertas[0] if abertas else None
    return FinancingOut(
        id=f.id, title=f.title, description=f.description,
        status=getattr(f.status, "value", f.status), method=getattr(f.method, "value", f.method),
        currency=f.currency, amount=f.total_amount, monthly_rate=format(Decimal(f.interest_rate), "f"),
        start_date=f.start_date, installments=f.installments_count,
        paid_installments=len(parcelas) - len(abertas), remaining_installments=len(abertas),
        outstanding=sum((Decimal(p.principal_amount) for p in abertas), Decimal("0.00")),
        next_due_date=proxima.due_date if proxima else None,
        next_amount=proxima.total_amount if proxima else None,
        overdue_count=sum(1 for p in abertas if p.due_date < hoje),
        app_url=app_url("/me/financing"),
    )


def _meus(call: ToolCall) -> list[Financing]:
    return list(call.session.exec(
        select(Financing)
        .where(personal_scope(Financing.owner_user_id, call.identity.user_id), Financing.deleted_at.is_(None))
        .order_by(Financing.title, Financing.id)
    ).all())


def resolve_financing(call: ToolCall, financing_id: Optional[int], financing: Optional[str]) -> Financing:
    todos = _meus(call)
    if financing_id is not None:
        for f in todos:
            if f.id == financing_id:
                return f
        raise McpToolError(ErrorCode.NOT_FOUND, "Financiamento não encontrado.", details={"financing_id": financing_id})
    if financing:
        escolhido = resolve.pick("financiamento", financing, [resolve.Match(f.id, f.title) for f in todos], id_param="financing_id")
        return next(f for f in todos if f.id == escolhido.id)
    if len(todos) == 1:
        return todos[0]
    if not todos:
        raise McpToolError(ErrorCode.NOT_FOUND, "Você não tem financiamento cadastrado.")
    raise McpToolError(
        ErrorCode.AMBIGUOUS,
        "Você tem mais de um financiamento. Pergunte qual e informe `financing` ou `financing_id`.",
        candidates=[{"id": f.id, "name": f.title} for f in todos],
        details={"kind": "financiamento", "id_param": "financing_id"},
    )


# --- financings_list -------------------------------------------------------------------

class FinancingsIn(ToolInput):
    financing: Optional[str] = Field(None, max_length=120, description="Um financiamento (nome): devolve também o cronograma.")
    financing_id: Optional[int] = None
    limit: int = Field(24, ge=1, le=120, description="Parcelas do cronograma por página.")
    cursor: Optional[str] = Field(None, max_length=512)

    @model_validator(mode="after")
    def _par(self):
        if self.financing is not None and self.financing_id is not None:
            raise ValueError("informe financing ou financing_id, não os dois")
        return self


class FinancingsOut(BaseModel):
    financings: List[FinancingOut]
    schedule: List[InstallmentOut] = Field(default_factory=list, description="Cronograma (quando um financiamento foi pedido).")
    next_cursor: Optional[str] = None


@tool(
    name="financings_list",
    title="Financiamentos",
    description=(
        "Lista seus financiamentos (casa, carro) com saldo devedor, parcelas pagas e restantes, a "
        "próxima parcela e atrasos. Com `financing`, traz também o cronograma (principal, juros, saldo "
        "depois de cada parcela, paga ou não), paginado.\n"
        "Use quando: 'quanto falta do financiamento?', 'qual a próxima parcela?', antes de pagar ou "
        "desfazer uma parcela (financings_installment).\n"
        "Não use quando: quiser tudo que vence no mês, de todas as origens (payables_list)."
    ),
    input_model=FinancingsIn,
    output_model=FinancingsOut,
    scope=escopos.FINANCE_READ,
    kind="read",
    read_only=True,
    destructive=False,
    idempotent=True,
    cost=2,
)
def financings_list(call: ToolCall) -> ToolOutput:
    a: FinancingsIn = call.args
    if a.financing is None and a.financing_id is None:
        saida = FinancingsOut(financings=[financing_out(call, f) for f in _meus(call)])
        return ToolOutput(
            structured=saida,
            summary=f"{len(saida.financings)} financiamento(s).",
            entity_type="financing",
            entity_ids=[f.id for f in saida.financings],
        )
    f = resolve_financing(call, a.financing_id, a.financing)
    parcelas = _parcelas(call, f)
    impressao = f"fin:{f.id}"
    try:
        inicio = transaction_query.decode_cursor(a.cursor, impressao) if a.cursor else 0
    except transaction_query.InvalidCursor as exc:
        raise McpToolError(ErrorCode.VALIDATION_ERROR, str(exc))
    pagina = parcelas[inicio:inicio + a.limit]
    contas = _nomes_contas(call, (p.account_id for p in pagina))
    hoje = today_local()
    resumo = financing_out(call, f, parcelas)
    saida = FinancingsOut(
        financings=[resumo],
        schedule=[
            InstallmentOut(
                number=p.installment_number, due_date=p.due_date, principal=p.principal_amount,
                interest=p.interest_amount, total=p.total_amount, remaining_balance=p.remaining_balance,
                paid=p.is_paid, paid_on=local_day(p.paid_at) if p.paid_at else None,
                account=Ref(id=p.account_id, name=contas.get(p.account_id, "?")) if p.account_id else None,
                overdue=not p.is_paid and p.due_date < hoje,
            )
            for p in pagina
        ],
        next_cursor=transaction_query.encode_cursor(inicio + a.limit, impressao) if inicio + a.limit < len(parcelas) else None,
    )
    return ToolOutput(
        structured=saida,
        summary=(
            f"{f.title}: saldo devedor {fmt_brl(resumo.outstanding, f.currency)}, "
            f"{resumo.remaining_installments} de {resumo.installments} parcela(s) em aberto"
            + (f"; próxima {fmt_brl(resumo.next_amount, f.currency)} em {resumo.next_due_date.strftime('%d/%m/%Y')}." if resumo.next_due_date else ".")
        ),
        entity_type="financing",
        entity_ids=[f.id],
    )


# --- financings_installment ----------------------------------------------------------------

class InstallmentActionIn(ToolInput):
    action: Literal["pay", "unpay"] = Field(description="pay = paguei a parcela; unpay = desfazer (marquei errado).")
    financing: Optional[str] = Field(None, max_length=120)
    financing_id: Optional[int] = None
    installment: Optional[int] = Field(
        None, ge=1, le=600, description="Número da parcela. Omitido: pay = a próxima em aberto; unpay = a última paga.",
    )
    account: Optional[str] = Field(None, max_length=120, description="pay: conta de onde saiu o dinheiro.")
    account_id: Optional[int] = None
    paid_on: Optional[CivilDate] = Field(None, description="pay: dia do pagamento. Omitido = hoje.")
    space: Optional[str] = Field(
        None, max_length=120, description="pay: lança também a despesa neste espaço (para dividir). Omitido = só marca como paga.",
    )
    space_id: Optional[int] = None

    @model_validator(mode="after")
    def _coerente(self):
        for x, y in (("financing", "financing_id"), ("account", "account_id"), ("space", "space_id")):
            if getattr(self, x) is not None and getattr(self, y) is not None:
                raise ValueError(f"informe {x} ou {y}, não os dois")
        if self.action == "unpay" and any(
            v is not None for v in (self.account, self.account_id, self.paid_on, self.space, self.space_id)
        ):
            raise ValueError("unpay só precisa do financiamento e da parcela")
        return self


class InstallmentActionOut(BaseModel):
    financing: FinancingOut
    installment: int
    action: str
    transaction_id: Optional[int] = Field(None, description="pay com espaço: a despesa lançada.")


@tool(
    name="financings_installment",
    title="Pagar/desfazer parcela",
    description=(
        "Marca uma parcela de financiamento como paga (`action=pay`, na conta e na data informadas; "
        "com `space`, lança também a despesa naquele espaço) ou desfaz o pagamento (`action=unpay`: a "
        "parcela volta a aberta e a despesa lançada some).\n"
        "Use quando: 'paguei a parcela do carro', 'marquei a parcela errada, desfaça'.\n"
        "Não use quando: quiser cadastrar, alterar ou quitar o contrato inteiro (isso é no app)."
    ),
    input_model=InstallmentActionIn,
    output_model=InstallmentActionOut,
    scope=escopos.ACCOUNTS_WRITE,
    kind="write",
    read_only=False,
    destructive=True,
    idempotent=True,
    cost=3,
    invoking="Atualizando a parcela…",
    invoked="Parcela atualizada",
    examples=({"action": "pay", "financing": "Carro", "account": "Itaú"}, {"action": "unpay", "financing": "Carro", "installment": 12}),
)
def financings_installment(call: ToolCall) -> ToolOutput:
    a: InstallmentActionIn = call.args
    me = call.identity.user_id
    f = resolve_financing(call, a.financing_id, a.financing)
    parcelas = _parcelas(call, f)
    numero = a.installment
    if numero is None:
        if a.action == "pay":
            abertas = [p for p in parcelas if not p.is_paid]
            if not abertas:
                raise McpToolError(ErrorCode.BUSINESS_RULE_VIOLATION, f"{f.title} não tem parcela em aberto.")
            numero = abertas[0].installment_number
        else:
            pagas = [p for p in parcelas if p.is_paid]
            if not pagas:
                raise McpToolError(ErrorCode.BUSINESS_RULE_VIOLATION, f"{f.title} não tem parcela paga para desfazer.")
            numero = pagas[-1].installment_number
    tx_id = None
    try:
        if a.action == "pay":
            conta = resolve.resolve_account(call.session, me, account_id=a.account_id, account=a.account)
            espaco = resolve.resolve_space(call.session, me, space_id=a.space_id, space=a.space)
            if espaco is not None:
                from app.mcp.writes import membership_for_write

                membership_for_write(call, espaco.id)
            tx_id = fin_cmd.pay_installment(call.session, me, f.id, numero, InstallmentPayRequest(
                workspace_id=espaco.id if espaco else None,
                paid_at=civil_instant(a.paid_on) if a.paid_on else None,
                account_id=conta.id if conta else None,
            ))
        else:
            fin_cmd.unpay_installment(call.session, me, f.id, numero)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise McpToolError(ErrorCode.NOT_FOUND, str(exc.detail), details={"installment": numero})
        raise
    call.session.flush()
    call.session.expire_all()
    f = call.session.get(Financing, f.id)
    saida = InstallmentActionOut(financing=financing_out(call, f), installment=numero, action=a.action, transaction_id=tx_id)
    feito = "paga" if a.action == "pay" else "reaberta"
    return ToolOutput(
        structured=saida,
        summary=f"Parcela {numero} de {f.title} {feito}. Saldo devedor: {fmt_brl(saida.financing.outstanding, f.currency)}.",
        entity_type="financing",
        entity_ids=[f.id] + ([tx_id] if tx_id else []),
    )
