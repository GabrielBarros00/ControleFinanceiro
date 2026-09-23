"""Conciliar extrato: o agente lê o extrato (PDF, foto, texto colado) e o app decide.

O agente é bom em EXTRAIR linhas de um extrato; o app é quem sabe o que já está
lançado. Então o trabalho se divide em duas tools, com as regras do import de
CSV do app (ADR 0008):

- `imports_preview` (só leitura): para cada linha, diz se ela JÁ FOI importada
  (mesma impressão digital: dia, centavos, título — seria pulada no commit) e se
  PARECE um lançamento existente (mesmo dia, valor e título — a heurística que a
  tela de importação mostra). Nada é gravado.
- `imports_commit`: grava o lote com a decisão por linha (`import`/`ignore`),
  idempotente por impressão digital, e cada lançamento nasce como no import do
  app: pago por você, 100% seu, liquidado na data.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator
from sqlmodel import select

from app.core.config import settings
from app.domain.dates import civil_instant
from app.mcp import resolve
from app.mcp.dates import CivilDate
from app.mcp.errors import ErrorCode, McpToolError
from app.mcp.money import MoneyIn, MoneyOut, fmt_brl
from app.mcp.registry import ToolCall, ToolInput, ToolOutput, tool
from app.mcp.schemas import Ref
from app.mcp.writes import IdempotencyKey, membership_for_write
from app.models.import_batch import ImportBatch, ImportRow, ImportRowStatus, compute_fingerprint
from app.models.workspace import Workspace
from app.schemas.imports import CommitRequest, CommitRow
from app.services.commands import imports as imp_cmd
from app.services.oauth import scopes as escopos

MAX_LINHAS = settings.MCP_BULK_MAX_ITEMS


class StatementLineIn(ToolInput):
    line: Optional[int] = Field(None, ge=1, description="Número da linha no extrato (para você se orientar).")
    date: CivilDate
    title: str = Field(min_length=1, max_length=200, description="Descrição como está no extrato.")
    amount: MoneyIn = Field(description="Valor da SAÍDA (positivo). Entradas não são importadas aqui.")


class _EspacoIn(ToolInput):
    space: Optional[str] = Field(None, max_length=120, description="Espaço onde os lançamentos entram.")
    space_id: Optional[int] = None

    @model_validator(mode="after")
    def _par(self):
        if self.space is not None and self.space_id is not None:
            raise ValueError("informe space ou space_id, não os dois")
        return self


class ImportPreviewIn(_EspacoIn):
    rows: List[StatementLineIn] = Field(min_length=1, max_length=MAX_LINHAS)


class PreviewLine(BaseModel):
    line: Optional[int] = None
    date: dt.date
    title: str
    amount: MoneyOut
    already_imported: bool = Field(description="Já importada antes (seria pulada no commit).")
    possible_duplicate: bool = Field(description="Parece um lançamento que já existe (mesmo dia, valor e título).")


class ImportPreviewOut(BaseModel):
    space: Ref
    rows: List[PreviewLine]
    new_count: int = Field(description="Linhas sem sinal de já existir.")
    already_imported_count: int
    possible_duplicate_count: int


def _preparar(ws_id: int, linhas: list[StatementLineIn]) -> list[dict]:
    return [
        {
            "line": x.line,
            "title": x.title.strip()[:200],
            "total_amount": x.amount,
            "transaction_date": civil_instant(x.date),
            "date": x.date,
        }
        for x in linhas
    ]


@tool(
    name="imports_preview",
    title="Conferir linhas de extrato",
    description=(
        "Confere linhas de um extrato bancário/cartão contra o que já está no app, sem gravar nada: "
        "marca o que já foi importado e o que parece já lançado.\n"
        "Use quando: o usuário colar ou enviar um extrato e pedir para conciliar/importar. Extraia as "
        "linhas de SAÍDA (data, descrição, valor) e chame esta tool antes de imports_commit.\n"
        "Não use quando: for registrar um gasto isolado (transactions_create)."
    ),
    input_model=ImportPreviewIn,
    output_model=ImportPreviewOut,
    scope=escopos.FINANCE_READ,
    kind="read",
    read_only=True,
    destructive=False,
    idempotent=True,
    cost=3,
    invoking="Conferindo o extrato…",
    invoked="Extrato conferido",
    examples=({"space": "Meu espaço", "rows": [{"date": "2026-09-20", "title": "PADARIA PAO QUENTE", "amount": "12.50"}]},),
)
def imports_preview(call: ToolCall) -> ToolOutput:
    a: ImportPreviewIn = call.args
    ref = resolve.require_space(call.session, call.identity.user_id, space_id=a.space_id, space=a.space)
    linhas = _preparar(ref.id, a.rows)
    imp_cmd._mark_duplicates(call.session, ref.id, linhas)
    impressoes = {compute_fingerprint(ref.id, x["transaction_date"], x["total_amount"], x["title"]) for x in linhas}
    ja = set(call.session.exec(
        select(ImportRow.fingerprint).where(
            ImportRow.workspace_id == ref.id,
            ImportRow.status == ImportRowStatus.imported,
            ImportRow.fingerprint.in_(list(impressoes)),
        )
    ).all())
    saida_linhas = []
    for x in linhas:
        fp = compute_fingerprint(ref.id, x["transaction_date"], x["total_amount"], x["title"])
        saida_linhas.append(PreviewLine(
            line=x["line"], date=x["date"], title=x["title"], amount=x["total_amount"],
            already_imported=fp in ja, possible_duplicate=bool(x.get("duplicate")),
        ))
    novas = sum(1 for x in saida_linhas if not x.already_imported and not x.possible_duplicate)
    saida = ImportPreviewOut(
        space=Ref(id=ref.id, name=ref.workspace.name),
        rows=saida_linhas,
        new_count=novas,
        already_imported_count=sum(1 for x in saida_linhas if x.already_imported),
        possible_duplicate_count=sum(1 for x in saida_linhas if x.possible_duplicate and not x.already_imported),
    )
    return ToolOutput(
        structured=saida,
        summary=(
            f"{len(saida_linhas)} linha(s): {novas} nova(s), {saida.already_imported_count} já importada(s), "
            f"{saida.possible_duplicate_count} parecida(s) com lançamentos existentes. Mostre ao usuário e "
            "confirme o que importar antes de imports_commit."
        ),
        space_id=ref.id,
    )


# --- imports_commit ------------------------------------------------------------------------

class CommitLineIn(StatementLineIn):
    decision: Literal["import", "ignore"] = Field("import", description="`ignore` registra a linha como ignorada.")


class ImportCommitIn(_EspacoIn):
    idempotency_key: IdempotencyKey
    label: Optional[str] = Field(None, max_length=120, description="Nome do lote (ex.: \"Extrato Itaú setembro\").")
    rows: List[CommitLineIn] = Field(min_length=1, max_length=MAX_LINHAS)


class ImportCommitOut(BaseModel):
    batch_id: int
    space: Ref
    imported: int
    ignored: int
    duplicate: int = Field(description="Puladas por já terem sido importadas antes.")
    skipped: int
    transaction_ids: List[int]
    replayed: bool = False


def _commit_out(call: ToolCall, batch: ImportBatch, *, replayed: bool = False) -> ImportCommitOut:
    espaco = call.session.get(Workspace, batch.workspace_id)
    ids = list(call.session.exec(
        select(ImportRow.transaction_id)
        .where(ImportRow.batch_id == batch.id, ImportRow.transaction_id.is_not(None))
        .order_by(ImportRow.id)
    ).all())
    return ImportCommitOut(
        batch_id=batch.id, space=Ref(id=espaco.id, name=espaco.name),
        imported=batch.imported_count, ignored=batch.ignored_count,
        duplicate=batch.duplicate_count, skipped=batch.skipped_count,
        transaction_ids=ids, replayed=replayed,
    )


def _replay_commit(call: ToolCall, ref: dict) -> ToolOutput:
    batch = call.session.get(ImportBatch, int(ref["batch_id"]))
    if batch is None or batch.created_by_user_id != call.identity.user_id:
        raise McpToolError(ErrorCode.CONFLICT, "Operação já processada com esta idempotency_key.")
    saida = _commit_out(call, batch, replayed=True)
    return ToolOutput(
        structured=saida,
        summary="Este lote já tinha sido importado (mesma idempotency_key); nada novo foi gravado.",
        entity_type="transaction",
        entity_ids=saida.transaction_ids,
        space_id=batch.workspace_id,
    )


@tool(
    name="imports_commit",
    title="Importar linhas de extrato",
    description=(
        "Grava as linhas de extrato confirmadas pelo usuário como lançamentos (pagos por você, 100% "
        "seus, já liquidados na data), num lote. Linhas já importadas antes são puladas sozinhas.\n"
        "Use quando: depois de imports_preview, o usuário confirmar quais linhas importar.\n"
        "Não use quando: não houver confirmação do usuário, ou para despesas divididas/no cartão "
        "(transactions_create, que tem divisão e fatura).\n"
        "Mande `decision: ignore` nas linhas que o usuário descartou (ficam registradas como ignoradas)."
    ),
    input_model=ImportCommitIn,
    output_model=ImportCommitOut,
    scope=escopos.TRANSACTIONS_WRITE,
    kind="write",
    read_only=False,
    destructive=False,
    idempotent=True,
    cost=5,
    idempotency_key=True,
    replay=_replay_commit,
    invoking="Importando…",
    invoked="Importação concluída",
    examples=({"idempotency_key": "a9b8c7d6-0001", "space": "Meu espaço", "label": "Extrato Itaú",
               "rows": [{"date": "2026-09-20", "title": "PADARIA PAO QUENTE", "amount": "12.50"}]},),
)
def imports_commit(call: ToolCall) -> ToolOutput:
    a: ImportCommitIn = call.args
    ref = resolve.require_space(call.session, call.identity.user_id, space_id=a.space_id, space=a.space)
    membership = membership_for_write(call, ref.id)
    corpo = CommitRequest(
        filename=a.label or "Importado por agente de IA",
        rows=[
            CommitRow(
                line=x.line, title=x.title, total_amount=x.amount,
                transaction_date=civil_instant(x.date), decision=x.decision,
            )
            for x in a.rows
        ],
    )
    resultado = imp_cmd.commit_import(call.session, ref.id, corpo, membership)
    batch = call.session.get(ImportBatch, resultado["batch_id"])
    saida = _commit_out(call, batch)
    total = sum((x.amount for x in a.rows if x.decision == "import"), Decimal("0"))
    return ToolOutput(
        structured=saida,
        summary=(
            f"Importadas {saida.imported} linha(s) em {ref.workspace.name}"
            f" (de {fmt_brl(total)} marcados para importar); {saida.duplicate} já existiam, "
            f"{saida.ignored} ignorada(s), {saida.skipped} inválida(s)."
        ),
        entity_type="transaction",
        entity_ids=saida.transaction_ids,
        space_id=ref.id,
        result_ref={"batch_id": batch.id},
    )
