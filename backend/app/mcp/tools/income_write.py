"""Renda pessoal: registrar e atualizar (inclusive "recebi", "não veio", cancelar).

Renda é estritamente pessoal (ADR 0021): não tem espaço nem divisão, e a conta de
destino é sempre de quem recebeu. Estrangeira é convertida na entrada pela mesma
função do app, na data do recebimento (sem IOF).
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from app.domain.dates import civil_instant, today_local
from app.mcp import resolve
from app.mcp.dates import CivilDate
from app.mcp.errors import ErrorCode, McpToolError
from app.mcp.money import MoneyIn, fmt_brl
from app.mcp.registry import ToolCall, ToolInput, ToolOutput, tool
from app.mcp.tools.obligations import IncomeOut, income_out
from app.mcp.writes import IdempotencyKey
from app.models.income import Income
from app.schemas.common import DESCRIPTION_MAX, TITLE_MAX
from app.schemas.income import IncomeCreate, IncomeReceiveRequest, IncomeUpdate
from app.services.commands import income as inc_cmd
from app.services.oauth import scopes as escopos

_CATEGORIA = Field(None, max_length=60, description="Rótulo livre da renda (ex.: \"Salário\", \"Freela\").")


def _renda(call: ToolCall, income_id: int) -> Income:
    renda = call.session.get(Income, income_id)
    # Renda de outra pessoa é indistinguível de inexistente.
    if renda is None or renda.deleted_at is not None or renda.user_id != call.identity.user_id:
        raise McpToolError(ErrorCode.NOT_FOUND, "Renda não encontrada.", details={"income_id": income_id})
    return renda


def _conta_id(call: ToolCall, account_id: Optional[int], account: Optional[str]) -> Optional[int]:
    conta = resolve.resolve_account(call.session, call.identity.user_id, account_id=account_id, account=account)
    return conta.id if conta else None


class IncomeResult(BaseModel):
    income: IncomeOut
    replayed: bool = False


def _frase(r: IncomeOut) -> str:
    estado = {"received": "recebida", "expected": "prevista", "overdue": "atrasada", "cancelled": "cancelada"}[r.status]
    return f"{r.title}: {fmt_brl(r.amount, r.currency)} em {r.date.strftime('%d/%m/%Y')} ({estado})."


# --- income_create -----------------------------------------------------------------

class IncomeCreateIn(ToolInput):
    idempotency_key: IdempotencyKey
    title: str = Field(min_length=1, max_length=TITLE_MAX, description="Ex.: \"Salário\", \"Freela site\".")
    amount: MoneyIn
    date: Optional[CivilDate] = Field(None, description="Data da renda (competência). Omitido = hoje.")
    currency: Optional[str] = Field(None, pattern=r"^[A-Za-z]{3}$", description="Moeda ISO; estrangeira é convertida na data.")
    category: Optional[str] = _CATEGORIA
    description: Optional[str] = Field(None, max_length=DESCRIPTION_MAX)
    account: Optional[str] = Field(None, max_length=120, description="Conta onde o dinheiro caiu/vai cair.")
    account_id: Optional[int] = None
    received: Optional[bool] = Field(
        None, description="Já caiu na conta? Omitido = o app decide pela data (passado/hoje = recebida).",
    )

    @model_validator(mode="after")
    def _par(self):
        if self.account is not None and self.account_id is not None:
            raise ValueError("informe account ou account_id, não os dois")
        return self


def _replay_income(call: ToolCall, ref: dict) -> ToolOutput:
    saida = income_out(_renda(call, int(ref["income_id"])))
    return ToolOutput(
        structured=IncomeResult(income=saida, replayed=True),
        summary="Esta renda já tinha sido registrada (mesma idempotency_key); nada novo foi criado. " + _frase(saida),
        entity_type="income",
        entity_ids=[saida.id],
    )


@tool(
    name="income_create",
    title="Registrar renda",
    description=(
        "Registra uma entrada de dinheiro pessoal: salário, freela, reembolso, venda. Renda é sua, não "
        "de um espaço, e não se divide.\n"
        "Use quando: o usuário disser que recebeu ou vai receber dinheiro (\"caiu meu salário de "
        "R$ 5.000\", \"vou receber R$ 800 do freela dia 10\").\n"
        "Não use quando: alguém te pagou uma dívida de despesa dividida (settlements_create) ou foi "
        "transferência entre suas contas (transfers_create)."
    ),
    input_model=IncomeCreateIn,
    output_model=IncomeResult,
    scope=escopos.INCOME_WRITE,
    kind="write",
    read_only=False,
    destructive=False,
    idempotent=True,
    cost=3,
    idempotency_key=True,
    replay=_replay_income,
    invoking="Registrando a renda…",
    invoked="Renda registrada",
    examples=({"idempotency_key": "d8e9f0a1-0001", "title": "Salário", "amount": "5000.00", "account": "Itaú"},),
)
def income_create(call: ToolCall) -> ToolOutput:
    a: IncomeCreateIn = call.args
    renda = inc_cmd.create_income(call.session, call.identity.user_id, IncomeCreate(
        title=a.title,
        description=a.description,
        amount=a.amount,
        currency=a.currency.upper() if a.currency else None,
        received_at=civil_instant(a.date or today_local()),
        category=a.category,
        account_id=_conta_id(call, a.account_id, a.account),
        received=a.received,
    ))
    saida = income_out(renda)
    return ToolOutput(
        structured=IncomeResult(income=saida),
        summary="Renda registrada. " + _frase(saida),
        entity_type="income",
        entity_ids=[renda.id],
        result_ref={"income_id": renda.id},
    )


# --- income_update -------------------------------------------------------------------

class IncomeUpdateIn(ToolInput):
    income_id: int
    title: Optional[str] = Field(None, min_length=1, max_length=TITLE_MAX)
    description: Optional[str] = Field(None, max_length=DESCRIPTION_MAX)
    amount: Optional[MoneyIn] = Field(
        None,
        description=(
            "Novo valor, na moeda DA RENDA: a de `currency`, se informada; senão a original "
            "(`original_currency`) quando a renda foi convertida."
        ),
    )
    currency: Optional[str] = Field(
        None, pattern=r"^[A-Za-z]{3}$", description="Moeda ISO; estrangeira é reconvertida na data."
    )
    date: Optional[CivilDate] = Field(None, description="Nova data da renda (competência).")
    category: Optional[str] = _CATEGORIA
    account: Optional[str] = Field(None, max_length=120)
    account_id: Optional[int] = None
    status: Optional[Literal["received", "expected", "cancelled"]] = Field(
        None,
        description=(
            "`received` = caiu na conta (use `received_on`/`account` se souber); `expected` = desfaz o "
            "\"recebi\"; `cancelled` = não veio e não virá (definitivo, continua visível)."
        ),
    )
    received_on: Optional[CivilDate] = Field(None, description="Dia em que caiu (com status=received). Omitido = hoje.")

    @model_validator(mode="after")
    def _coerencia(self):
        if self.account is not None and self.account_id is not None:
            raise ValueError("informe account ou account_id, não os dois")
        if self.received_on is not None and self.status != "received":
            raise ValueError("received_on só com status=received")
        if not self.model_dump(exclude_unset=True, exclude={"income_id"}):
            raise ValueError("nada para alterar: informe ao menos um campo")
        return self


class IncomeUpdateResult(BaseModel):
    income: IncomeOut
    previous: IncomeOut
    changed: List[str]


@tool(
    name="income_update",
    title="Atualizar renda",
    description=(
        "Altera uma renda sua (valor, data, título, categoria, conta) e/ou o estado dela: recebida, "
        "prevista de novo ou cancelada. Devolve como estava antes (`previous`).\n"
        "Use quando: o usuário disser \"o salário caiu\", \"o freela atrasou, ainda não recebi\", "
        "\"esse pagamento não vai vir\" ou pedir para corrigir uma renda. Pegue o `income_id` em income_list.\n"
        "Não use quando: for registrar uma renda nova (income_create)."
    ),
    input_model=IncomeUpdateIn,
    output_model=IncomeUpdateResult,
    scope=escopos.INCOME_WRITE,
    kind="write",
    read_only=False,
    destructive=True,
    idempotent=True,
    cost=3,
    invoking="Atualizando a renda…",
    invoked="Renda atualizada",
    examples=({"income_id": 12, "status": "received", "account": "Itaú"}, {"income_id": 12, "amount": "5200.00"}),
)
def income_update(call: ToolCall) -> ToolOutput:
    a: IncomeUpdateIn = call.args
    me = call.identity.user_id
    renda = _renda(call, a.income_id)
    antes = income_out(renda)
    campos = a.model_dump(exclude_unset=True, exclude={"income_id", "status", "received_on", "account", "account_id", "date"})
    if a.date is not None:
        campos["received_at"] = civil_instant(a.date)
    if "currency" in campos and campos["currency"]:
        campos["currency"] = campos["currency"].upper()
    if "description" in campos and campos["description"] == "":
        campos["description"] = None
    conta_id = _conta_id(call, a.account_id, a.account)
    if conta_id is not None and a.status != "received":
        campos["account_id"] = conta_id
    if campos:
        inc_cmd.update_income(call.session, me, renda.id, IncomeUpdate(**campos))
    if a.status == "received":
        inc_cmd.receive_income(call.session, me, renda.id, IncomeReceiveRequest(
            received_on=a.received_on or today_local(), account_id=conta_id,
        ))
    elif a.status == "expected":
        inc_cmd.unreceive_income(call.session, me, renda.id)
    elif a.status == "cancelled":
        inc_cmd.cancel_income(call.session, me, renda.id)
    call.session.flush()
    call.session.refresh(renda)
    depois = income_out(renda)
    a_json, d_json = antes.model_dump(mode="json"), depois.model_dump(mode="json")
    mudou = [k for k in d_json if k != "id" and a_json.get(k) != d_json.get(k)]
    return ToolOutput(
        structured=IncomeUpdateResult(income=depois, previous=antes, changed=mudou),
        summary=(f"Renda atualizada ({', '.join(mudou)}). " if mudou else "Nada mudou. ") + _frase(depois),
        entity_type="income",
        entity_ids=[renda.id],
    )
