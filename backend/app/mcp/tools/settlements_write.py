"""Acertos entre pessoas de um espaço: registrar e desfazer (ADR 0009/0031).

"O João me pagou os R$ 45 do jantar" não é renda nem despesa: é um ACERTO, que
reduz a dívida entre os dois dentro do espaço onde ela nasceu. As regras são as
do comando do app, sem atalho: o acerto segue a direção da dívida, não pode
passar dela (sobrepagar inventaria crédito) e um `member` só registra acerto em
que ele mesmo é quem pagou — "o João me pagou" registrado pela Alice exige que
ela seja admin do espaço (senão é o João quem registra, pelo app dele).
"""
from __future__ import annotations

import datetime as dt
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from app.domain.access_policy import has_full_access
from app.domain.dates import civil_instant, local_day
from app.domain.query_policy import workspace_base_currency
from app.mcp import resolve
from app.mcp.dates import CivilDate, MonthKey
from app.mcp.errors import ErrorCode, McpToolError
from app.mcp.money import MoneyIn, MoneyOut, fmt_brl
from app.mcp.registry import ToolCall, ToolInput, ToolOutput, tool
from app.mcp.schemas import Ref
from app.mcp.writes import IdempotencyKey, membership_for_write
from app.models.payment_account import PaymentAccount
from app.models.settlement import Settlement
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.common import DESCRIPTION_MAX
from app.schemas.settlement import SettlementCreate
from app.services.commands import settlements as st_cmd
from app.services.oauth import scopes as escopos


class SettlementOut(BaseModel):
    id: int
    space: Ref
    payer: Ref = Field(description="Quem pagou.")
    receiver: Ref = Field(description="Quem recebeu.")
    amount: MoneyOut
    currency: str
    month: Optional[str] = Field(None, description="Mês da dívida quitada (YYYY-MM), quando foi um acerto do mês.")
    date: dt.date
    note: Optional[str] = None
    account: Optional[Ref] = None
    replayed: bool = False


def _out(call: ToolCall, s: Settlement, *, replayed: bool = False) -> SettlementOut:
    nomes = {u.id: u.name for u in (call.session.get(User, s.from_user_id), call.session.get(User, s.to_user_id)) if u}
    espaco = call.session.get(Workspace, s.workspace_id)
    conta = call.session.get(PaymentAccount, s.from_account_id) if s.from_account_id else None
    return SettlementOut(
        id=s.id,
        space=Ref(id=espaco.id, name=espaco.name),
        payer=Ref(id=s.from_user_id, name=nomes.get(s.from_user_id, "?")),
        receiver=Ref(id=s.to_user_id, name=nomes.get(s.to_user_id, "?")),
        amount=s.amount,
        currency=workspace_base_currency(call.session, s.workspace_id),
        month=s.billing_month,
        date=local_day(s.settled_at),
        note=s.note,
        account=Ref(id=conta.id, name=conta.name) if conta and conta.owner_user_id == call.identity.user_id else None,
        replayed=replayed,
    )


def _frase(o: SettlementOut, me: int) -> str:
    quem = "Você" if o.payer.id == me else o.payer.name
    para = "você" if o.receiver.id == me else o.receiver.name
    mes = f" (dívida de {o.month})" if o.month else ""
    return f"{quem} pagou {fmt_brl(o.amount, o.currency)} a {para} no espaço {o.space.name}{mes}."


def _espaco_com(call: ToolCall, pessoa_nome: Optional[str], pessoa_id: Optional[int]) -> resolve.SpaceRef:
    return resolve.choose_space_for_people(
        call.session, call.identity.user_id,
        [pessoa_nome] if pessoa_nome else [], [pessoa_id] if pessoa_id is not None else [],
    )


# --- settlements_create -------------------------------------------------------------

class SettlementCreateIn(ToolInput):
    idempotency_key: IdempotencyKey
    person: Optional[str] = Field(None, max_length=120, description="A outra pessoa do acerto (membro do espaço).")
    person_id: Optional[int] = None
    direction: Literal["they_paid_me", "i_paid_them"] = Field(
        description="`they_paid_me` = a pessoa te pagou; `i_paid_them` = você pagou a pessoa.",
    )
    amount: MoneyIn = Field(description="Valor pago. Não pode passar da dívida (veja debts_summary).")
    space: Optional[str] = Field(None, max_length=120, description="Espaço da dívida. Omitido: o único que vocês dois compartilham.")
    space_id: Optional[int] = None
    month: Optional[MonthKey] = Field(None, description="Quitar a dívida de um mês específico (YYYY-MM). Omitido: a dívida acumulada.")
    date: Optional[CivilDate] = Field(None, description="Dia do pagamento. Omitido = agora.")
    account: Optional[str] = Field(None, max_length=120, description="Sua conta de onde saiu o dinheiro (só com i_paid_them).")
    account_id: Optional[int] = None
    note: Optional[str] = Field(None, max_length=DESCRIPTION_MAX)

    @model_validator(mode="after")
    def _coerencia(self):
        if (self.person is None) == (self.person_id is None):
            raise ValueError("informe person OU person_id")
        for a, b in (("space", "space_id"), ("account", "account_id")):
            if getattr(self, a) is not None and getattr(self, b) is not None:
                raise ValueError(f"informe {a} ou {b}, não os dois")
        if (self.account is not None or self.account_id is not None) and self.direction != "i_paid_them":
            raise ValueError("a conta só vale quando foi você quem pagou (i_paid_them)")
        return self


def _replay_settlement(call: ToolCall, ref: dict) -> ToolOutput:
    s = call.session.get(Settlement, int(ref["settlement_id"]))
    if s is None or s.created_by_user_id != call.identity.user_id:
        raise McpToolError(ErrorCode.CONFLICT, "Operação já processada com esta idempotency_key.")
    saida = _out(call, s, replayed=True)
    return ToolOutput(
        structured=saida,
        summary="Este acerto já tinha sido registrado (mesma idempotency_key); nada novo foi criado. " + _frase(saida, call.identity.user_id),
        entity_type="settlement",
        entity_ids=[s.id],
        space_id=s.workspace_id,
    )


@tool(
    name="settlements_create",
    title="Registrar acerto entre pessoas",
    description=(
        "Registra que uma pessoa pagou a outra para quitar (toda ou parte da) dívida de despesas "
        "divididas num espaço. Reduz \"quem deve a quem\".\n"
        "Use quando: o usuário disser \"o João me pagou os R$ 45\", \"acertei com a Maria\", "
        "\"paguei minha parte do aluguel pro João\". Confira o valor devido com debts_summary.\n"
        "Não use quando: for uma despesa nova (transactions_create) ou renda (income_create).\n"
        "O valor não pode passar da dívida naquela direção. Num espaço em que você é `member`, só é "
        "possível registrar acertos em que VOCÊ pagou (o outro lado registra o dele)."
    ),
    input_model=SettlementCreateIn,
    output_model=SettlementOut,
    scope=escopos.SETTLEMENTS_WRITE,
    kind="write",
    read_only=False,
    destructive=False,
    idempotent=True,
    cost=3,
    idempotency_key=True,
    replay=_replay_settlement,
    invoking="Registrando o acerto…",
    invoked="Acerto registrado",
    examples=({"idempotency_key": "e1f2a3b4-0001", "person": "João", "direction": "they_paid_me", "amount": "45.00"},),
)
def settlements_create(call: ToolCall) -> ToolOutput:
    a: SettlementCreateIn = call.args
    me = call.identity.user_id
    ref = resolve.resolve_space(call.session, me, space_id=a.space_id, space=a.space) or _espaco_com(call, a.person, a.person_id)
    membership = membership_for_write(call, ref.id)
    outro = resolve.resolve_person(call.session, workspace_id=ref.id, me_id=me, person=a.person, person_id=a.person_id)
    if outro.id == me:
        raise McpToolError(ErrorCode.VALIDATION_ERROR, "O acerto é entre você e OUTRA pessoa.")
    de, para = (outro.id, me) if a.direction == "they_paid_me" else (me, outro.id)
    conta = resolve.resolve_account(call.session, me, account_id=a.account_id, account=a.account)
    acerto = st_cmd.create_settlement(call.session, ref.id, SettlementCreate(
        from_user_id=de,
        to_user_id=para,
        amount=a.amount,
        note=a.note,
        billing_month=a.month,
        settled_at=civil_instant(a.date) if a.date else None,
        from_account_id=conta.id if conta else None,
    ), membership)
    saida = _out(call, acerto)
    return ToolOutput(
        structured=saida,
        summary="Acerto registrado. " + _frase(saida, me) + " Veja o saldo atualizado com debts_summary.",
        entity_type="settlement",
        entity_ids=[acerto.id],
        space_id=ref.id,
        result_ref={"settlement_id": acerto.id},
    )


# --- settlements_delete -------------------------------------------------------------

class SettlementDeleteIn(ToolInput):
    settlement_id: int


class SettlementDeleteOut(BaseModel):
    deleted: SettlementOut


@tool(
    name="settlements_delete",
    title="Desfazer acerto",
    description=(
        "Desfaz um acerto registrado por engano (a dívida volta a existir).\n"
        "Use quando: o usuário disser que um acerto foi lançado errado. Pegue o id em debts_summary "
        "(histórico de acertos) e confirme com o usuário qual é antes.\n"
        "Não use quando: o acerto estiver certo e a pessoa só quiser ver o saldo (debts_summary). "
        "Num espaço em que você é `member`, só dá para desfazer acertos que você registrou."
    ),
    input_model=SettlementDeleteIn,
    output_model=SettlementDeleteOut,
    scope=escopos.SETTLEMENTS_WRITE,
    kind="destructive",
    read_only=False,
    destructive=True,
    idempotent=True,
    cost=3,
    invoking="Desfazendo o acerto…",
    invoked="Acerto desfeito",
    examples=({"settlement_id": 31},),
)
def settlements_delete(call: ToolCall) -> ToolOutput:
    a: SettlementDeleteIn = call.args
    acerto = call.session.get(Settlement, a.settlement_id)
    if acerto is None or acerto.deleted_at is not None:
        raise McpToolError(ErrorCode.NOT_FOUND, "Acerto não encontrado.", details={"settlement_id": a.settlement_id})
    me = call.identity.user_id
    membership = membership_for_write(call, acerto.workspace_id)
    # Acerto tem dois lados: fora deles (e sem visão da casa inteira) é invisível.
    if me not in (acerto.from_user_id, acerto.to_user_id) and not has_full_access(membership):
        raise McpToolError(ErrorCode.NOT_FOUND, "Acerto não encontrado.", details={"settlement_id": a.settlement_id})
    saida = _out(call, acerto)
    st_cmd.delete_settlement(call.session, acerto.workspace_id, acerto.id, membership)
    return ToolOutput(
        structured=SettlementDeleteOut(deleted=saida),
        summary="Acerto desfeito: " + _frase(saida, me) + " A dívida voltou a contar.",
        entity_type="settlement",
        entity_ids=[acerto.id],
        space_id=acerto.workspace_id,
    )
