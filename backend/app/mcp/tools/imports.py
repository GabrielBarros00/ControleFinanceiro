"""Conciliar extrato: o agente lê o extrato (PDF, foto, texto colado) e o app decide.

O agente é bom em EXTRAIR linhas de um extrato; o app é quem sabe o que já está
lançado. Então o trabalho se divide em duas tools, com as regras do import do app:

- `imports_preview` (só leitura): para cada linha, diz se ela JÁ FOI importada
  (e o que ela criou ainda existe, ADR 0036) e se PARECE um lançamento existente.
  Nada é gravado.
- `imports_commit`: grava o lote com a decisão por linha (`import`/`ignore`).

Dois modos, os mesmos da tela:

- **Despesas de um espaço** (ADR 0008, sem `account`): toda linha é uma saída e
  vira lançamento pago por você, 100% seu, liquidado na data.
- **Extrato de uma conta** (ADR 0037, com `account`): cada linha tem sentido
  (`direction`) e classificação — despesa (num espaço), renda, transferência com
  outra conta sua ou pagamento de fatura —, e vira o registro que o app tem para
  aquilo, pelo comando da tela. A prévia sugere a classificação.

`imports_undo` desfaz um lote dos dois modos pelo MESMO comando do app, em duas
etapas: a prévia devolve o que sai e um token; só o token executa.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator
from sqlmodel import func, select

from app.core.config import settings
from app.domain.classificacao_de_extrato import sugerir
from app.domain.dates import civil_instant, local_day
from app.mcp import confirmation, resolve
from app.mcp.dates import CivilDate
from app.mcp.errors import ErrorCode, McpToolError
from app.mcp.money import MoneyIn, MoneyOut, fmt_brl
from app.mcp.ui import WIDGET_URI as WIDGET
from app.mcp.registry import ToolCall, ToolInput, ToolOutput, tool
from app.mcp.schemas import Ref
from app.mcp.writes import ConfirmationToken, IdempotencyKey, membership_for_write
from app.models.import_batch import (
    KIND_ACCOUNT,
    ImportBatch,
    ImportRow,
    ImportRowStatus,
    compute_account_fingerprint,
    compute_fingerprint,
)
from app.models.payment_account import PaymentAccount
from app.models.transaction import Transaction
from app.models.workspace import Workspace
from app.schemas.imports import AccountCommitRequest, AccountCommitRow, CommitRequest, CommitRow
from app.services.attachment_storage import free_keys
from app.services.commands import account_imports as acc_imp
from app.services.commands import imports as imp_cmd
from app.services.oauth import scopes as escopos

MAX_LINHAS = settings.MCP_BULK_MAX_ITEMS
Classificacao = Literal["expense", "income", "transfer", "statement_payment"]


class StatementLineIn(ToolInput):
    line: Optional[int] = Field(None, ge=1, description="Número da linha no extrato (para você se orientar).")
    date: CivilDate
    title: str = Field(min_length=1, max_length=200, description="Descrição como está no extrato.")
    amount: MoneyIn = Field(description="Positivo. Sem `account`, é uma saída; com `account`, o sentido vai em `direction`.")
    direction: Optional[Literal["in", "out"]] = Field(None, description="Só com `account`: in (entrou) | out (saiu, o padrão).")
    external_id: Optional[str] = Field(None, max_length=120, description="Só com `account`: o id da linha no banco, se houver.")


class _EspacoIn(ToolInput):
    space: Optional[str] = Field(None, max_length=120, description="Espaço dos lançamentos (com `account`: o padrão das despesas).")
    space_id: Optional[int] = None
    account: Optional[str] = Field(None, max_length=120, description="Extrato DE UMA CONTA sua (entradas, transferências, fatura).")
    account_id: Optional[int] = None

    @model_validator(mode="after")
    def _par(self):
        if self.space is not None and self.space_id is not None:
            raise ValueError("informe space ou space_id, não os dois")
        if self.account is not None and self.account_id is not None:
            raise ValueError("informe account ou account_id, não os dois")
        return self

    @property
    def de_conta(self) -> bool:
        return self.account is not None or self.account_id is not None


class ImportPreviewIn(_EspacoIn):
    rows: List[StatementLineIn] = Field(min_length=1, max_length=MAX_LINHAS)


class PreviewLine(BaseModel):
    line: Optional[int] = None
    date: dt.date
    title: str
    amount: MoneyOut
    direction: Optional[str] = None
    already_imported: bool = Field(description="Já importada, e o que ela criou ainda existe (seria pulada no commit).")
    possible_duplicate: bool = Field(description="Parece um lançamento que já existe (mesmo dia, valor e título).")
    suggestion: Optional[Classificacao] = Field(None, description="Com `account`: o palpite; confirme com o usuário.")
    suggested_card: Optional[Ref] = None
    suggested_account: Optional[Ref] = None


class ImportPreviewOut(BaseModel):
    space: Optional[Ref] = None
    account: Optional[Ref] = None
    rows: List[PreviewLine]
    new_count: int = Field(description="Linhas sem sinal de já existir.")
    already_imported_count: int
    possible_duplicate_count: int


def _preparar(linhas: list[StatementLineIn]) -> list[dict]:
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


def _conta(call: ToolCall, a: _EspacoIn) -> PaymentAccount:
    return resolve.resolve_account(call.session, call.identity.user_id, account_id=a.account_id, account=a.account)


def _previa_de_conta(call: ToolCall, a: ImportPreviewIn) -> ToolOutput:
    conta = _conta(call, a)
    externos, digitais = acc_imp._chaves_vivas(call.session, conta.id)
    outras = [c for c in resolve.user_accounts(call.session, call.identity.user_id) if c.id != conta.id]
    cartoes = resolve.user_cards(call.session, call.identity.user_id)
    nomes_contas = {c.id: c.name for c in outras}
    nomes_cartoes = {c.id: c.name for c in cartoes}
    linhas = []
    for x in a.rows:
        sentido = x.direction or "out"
        palpite = sugerir(x.title, sentido, nomes_contas.items(), nomes_cartoes.items())
        digital = compute_account_fingerprint(conta.id, civil_instant(x.date), sentido, x.amount, x.title.strip()[:200])
        linhas.append(PreviewLine(
            line=x.line, date=x.date, title=x.title.strip()[:200], amount=x.amount, direction=sentido,
            already_imported=bool(x.external_id and x.external_id in externos) or digital in digitais,
            possible_duplicate=False, suggestion=palpite.classification,
            suggested_card=Ref(id=palpite.card_id, name=nomes_cartoes[palpite.card_id]) if palpite.card_id else None,
            suggested_account=(
                Ref(id=palpite.counterpart_account_id, name=nomes_contas[palpite.counterpart_account_id])
                if palpite.counterpart_account_id else None
            ),
        ))
    ja = sum(1 for x in linhas if x.already_imported)
    tipos: Dict[str, int] = {}
    for x in linhas:
        if not x.already_imported:
            tipos[x.suggestion] = tipos.get(x.suggestion, 0) + 1
    saida = ImportPreviewOut(
        account=Ref(id=conta.id, name=conta.name), rows=linhas, new_count=len(linhas) - ja,
        already_imported_count=ja, possible_duplicate_count=0,
    )
    return ToolOutput(
        structured=saida,
        summary=(
            f"{len(linhas)} linha(s) do extrato de {conta.name}: {ja} já importada(s); palpites para as novas: "
            + (", ".join(f"{n} {t}" for t, n in sorted(tipos.items())) or "nenhuma")
            + ". Confirme a classificação com o usuário (despesa pede o espaço; transferência, a outra conta; "
            "pagamento de fatura, o cartão) antes de imports_commit."
        ),
    )


@tool(
    name="imports_preview",
    title="Conferir linhas de extrato",
    description=(
        "Confere linhas de um extrato contra o que já está no app, sem gravar nada: marca o que já "
        "foi importado e o que parece já lançado. Com `account` (extrato de UMA conta sua), cada linha "
        "tem `direction` e a prévia sugere a classificação: despesa, renda, transferência ou "
        "pagamento de fatura.\n"
        "Use quando: o usuário colar ou enviar um extrato e pedir para conciliar/importar. Chame antes "
        "de imports_commit.\n"
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
    examples=(
        {"space": "Meu espaço", "rows": [{"date": "2026-09-20", "title": "PADARIA PAO QUENTE", "amount": "12.50"}]},
        {"account": "Itaú", "rows": [{"date": "2026-09-05", "title": "PIX RECEBIDO", "amount": "900.00", "direction": "in"}]},
    ),
)
def imports_preview(call: ToolCall) -> ToolOutput:
    a: ImportPreviewIn = call.args
    if a.de_conta:
        return _previa_de_conta(call, a)
    ref = resolve.require_space(call.session, call.identity.user_id, space_id=a.space_id, space=a.space)
    linhas = _preparar(a.rows)
    imp_cmd._mark_duplicates(call.session, ref.id, linhas)
    impressoes = {compute_fingerprint(ref.id, x["transaction_date"], x["total_amount"], x["title"]) for x in linhas}
    # Já importada = o lançamento que a linha criou ainda existe (ADR 0036), a
    # mesma regra do commit: o desfeito ou excluído volta a entrar.
    ja = set(call.session.exec(
        select(ImportRow.fingerprint)
        .join(Transaction, Transaction.id == ImportRow.transaction_id)
        .where(
            ImportRow.workspace_id == ref.id,
            ImportRow.status == ImportRowStatus.imported,
            ImportRow.fingerprint.in_(list(impressoes)),
            Transaction.deleted_at.is_(None),
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
    classification: Optional[Classificacao] = Field(
        None, description="Só com `account`. Omitida: saiu = expense, entrou = income.",
    )
    space: Optional[str] = Field(None, max_length=120, description="Despesa: o espaço dela (senão o `space` do lote).")
    category: Optional[str] = Field(None, max_length=120, description="Despesa: categoria do espaço; renda: texto livre.")
    counterpart_account: Optional[str] = Field(None, max_length=120, description="Transferência: a OUTRA conta sua.")
    card: Optional[str] = Field(None, max_length=120, description="Pagamento de fatura: o cartão.")


class ImportCommitIn(_EspacoIn):
    idempotency_key: IdempotencyKey
    label: Optional[str] = Field(None, max_length=120, description="Nome do lote (ex.: \"Extrato Itaú setembro\").")
    rows: List[CommitLineIn] = Field(min_length=1, max_length=MAX_LINHAS)


class LineProblem(BaseModel):
    line: int
    reason: str


class ImportCommitOut(BaseModel):
    batch_id: int
    space: Optional[Ref] = None
    account: Optional[Ref] = None
    imported: int
    ignored: int
    duplicate: int = Field(description="Puladas por já terem sido importadas antes.")
    skipped: int
    transaction_ids: List[int]
    by_classification: Dict[str, int] = Field(default_factory=dict)
    problems: List[LineProblem] = Field(default_factory=list, description="Linhas que não entraram, com o motivo.")
    replayed: bool = False


def _commit_out(call: ToolCall, batch: ImportBatch, *, replayed: bool = False, extra: Optional[dict] = None) -> ImportCommitOut:
    ids = list(call.session.exec(
        select(ImportRow.transaction_id)
        .where(ImportRow.batch_id == batch.id, ImportRow.transaction_id.is_not(None))
        .order_by(ImportRow.id)
    ).all())
    espaco = call.session.get(Workspace, batch.workspace_id) if batch.workspace_id else None
    conta = call.session.get(PaymentAccount, batch.account_id) if batch.account_id else None
    if extra is None and batch.kind == KIND_ACCOUNT:
        linhas = call.session.exec(select(ImportRow).where(ImportRow.batch_id == batch.id)).all()
        por_tipo: Dict[str, int] = {}
        for r in linhas:
            if r.status == ImportRowStatus.imported:
                por_tipo[r.classification] = por_tipo.get(r.classification, 0) + 1
        extra = {
            "by_classification": por_tipo,
            "problems": [{"line": r.line or 0, "reason": r.reason or ""} for r in linhas if r.status == ImportRowStatus.skipped],
        }
    return ImportCommitOut(
        batch_id=batch.id,
        space=Ref(id=espaco.id, name=espaco.name) if espaco else None,
        account=Ref(id=conta.id, name=conta.name) if conta else None,
        imported=batch.imported_count, ignored=batch.ignored_count,
        duplicate=batch.duplicate_count, skipped=batch.skipped_count,
        transaction_ids=ids, replayed=replayed, **(extra or {}),
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


def _exige(call: ToolCall, escopo: str, para: str) -> None:
    if not call.identity.has(escopo):
        raise McpToolError(
            ErrorCode.PERMISSION_DENIED, f"Esta conexão não pode {para}. Reautorize com a permissão que falta.",
            required_scopes=[escopo],
        )


def _commit_de_conta(call: ToolCall, a: ImportCommitIn) -> ToolOutput:
    me = call.identity.user_id
    conta = _conta(call, a)
    classes = {
        (x.classification or ("expense" if (x.direction or "out") == "out" else "income"))
        for x in a.rows if x.decision == "import"
    }
    if classes - {"expense"}:
        _exige(call, escopos.ACCOUNTS_WRITE, "registrar renda, transferência ou pagamento de fatura numa conta")
    if "income" in classes:
        _exige(call, escopos.INCOME_WRITE, "registrar renda")
    padrao = resolve.require_space(call.session, me, space_id=a.space_id, space=a.space) if (a.space or a.space_id) else None
    linhas: List[AccountCommitRow] = []
    for x in a.rows:
        sentido = x.direction or "out"
        classe = x.classification or ("expense" if sentido == "out" else "income")
        espaco = resolve.require_space(call.session, me, space_id=None, space=x.space) if x.space else padrao
        categoria = None
        if classe == "expense" and x.category and espaco is not None:
            categoria = resolve.resolve_category(call.session, espaco.id, category_id=None, category=x.category)
        outra = resolve.resolve_account(call.session, me, account_id=None, account=x.counterpart_account) if x.counterpart_account else None
        cartao = resolve.resolve_card(call.session, me, card_id=None, card=x.card) if x.card else None
        linhas.append(AccountCommitRow(
            line=x.line, title=x.title, total_amount=x.amount, transaction_date=civil_instant(x.date),
            direction=sentido, external_id=x.external_id, decision=x.decision, classification=classe,
            space_id=espaco.id if espaco else None, category_id=categoria.id if categoria else None,
            income_category=x.category if classe == "income" else None,
            counterpart_account_id=outra.id if outra else None, card_id=cartao.id if cartao else None,
        ))
    resultado = acc_imp.commit_account_statement(call.session, me, AccountCommitRequest(
        account_id=conta.id, filename=a.label or "Extrato importado por agente de IA", rows=linhas,
    ))
    batch = call.session.get(ImportBatch, resultado["batch_id"])
    saida = _commit_out(call, batch, extra={"by_classification": resultado["by_classification"], "problems": resultado["problems"]})
    tipos = ", ".join(f"{n} {t}" for t, n in sorted(resultado["by_classification"].items())) or "nada"
    return ToolOutput(
        structured=saida,
        summary=(
            f"Extrato de {conta.name}: entraram {tipos}; {saida.duplicate} já existiam, {saida.ignored} ignorada(s), "
            f"{saida.skipped} não entraram" + (" (veja `problems`)." if saida.skipped else ".")
        ),
        entity_type="import",
        entity_ids=[batch.id],
        result_ref={"batch_id": batch.id},
    )


@tool(
    name="imports_commit",
    title="Importar linhas de extrato",
    description=(
        "Grava as linhas confirmadas pelo usuário, num lote. Sem `account`: lançamentos pagos por você, "
        "100% seus, liquidados. Com `account`: cada linha vira o que ela é (classification): despesa no "
        "espaço, renda na conta, transferência com `counterpart_account` ou pagamento da fatura do "
        "`card`. Linhas já importadas são puladas; as que não podem entrar voltam em `problems`.\n"
        "Use quando: depois de imports_preview, o usuário confirmar o que importar.\n"
        "Não use quando: não houver confirmação do usuário, ou para despesa dividida/no cartão "
        "(transactions_create)."
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
    ui=WIDGET,
    app_callable=True,
    meta={"openai/widgetDescription": "O componente mostra o que entrou e oferece desfazer a importação. Confirme em uma frase."},
)
def imports_commit(call: ToolCall) -> ToolOutput:
    a: ImportCommitIn = call.args
    if a.de_conta:
        return _commit_de_conta(call, a)
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


# --- imports_list --------------------------------------------------------------------------

class ImportsListIn(ToolInput):
    batch_id: Optional[int] = Field(None, ge=1, description="Um lote: devolve também as linhas.")
    limit: int = Field(20, ge=1, le=100, description="Lotes (sem batch_id) ou linhas (com batch_id) por página.")
    cursor: Optional[str] = Field(None, max_length=512)


class ImportBatchOut(BaseModel):
    id: int
    kind: str = Field(description="expenses (despesas de um espaço) | account (extrato de uma conta)")
    space: Optional[Ref] = None
    account: Optional[Ref] = None
    filename: Optional[str] = None
    imported_on: dt.date
    total_rows: int
    imported: int
    ignored: int
    duplicates: int
    skipped: int
    live_transactions: int = Field(description="O que o lote criou e ainda existe (lançamentos; no extrato, também rendas etc.).")


class ImportRowOut(BaseModel):
    line: Optional[int] = None
    date: dt.date
    title: str
    amount: MoneyOut
    direction: Optional[str] = None
    classification: Optional[str] = None
    status: str = Field(description="imported | ignored | duplicate | skipped")
    transaction_id: Optional[int] = None
    reason: Optional[str] = None


class ImportsListOut(BaseModel):
    batches: List[ImportBatchOut]
    rows: List[ImportRowOut] = Field(default_factory=list)
    next_cursor: Optional[str] = None


def _vivos_do_lote(call: ToolCall, b: ImportBatch) -> int:
    if b.kind == KIND_ACCOUNT:
        return len(acc_imp._vivas(call.session, [b.id]))
    return int(call.session.exec(
        select(func.count()).select_from(ImportRow)
        .join(Transaction, Transaction.id == ImportRow.transaction_id)
        .where(ImportRow.batch_id == b.id, Transaction.deleted_at.is_(None))
    ).one())


def _lote_out(call: ToolCall, b: ImportBatch, espacos: dict[int, str]) -> ImportBatchOut:
    conta = call.session.get(PaymentAccount, b.account_id) if b.account_id else None
    return ImportBatchOut(
        id=b.id, kind=b.kind,
        space=Ref(id=b.workspace_id, name=espacos.get(b.workspace_id, "?")) if b.workspace_id else None,
        account=Ref(id=conta.id, name=conta.name) if conta else None,
        filename=b.filename, imported_on=local_day(b.created_at), total_rows=b.total_rows,
        imported=b.imported_count, ignored=b.ignored_count, duplicates=b.duplicate_count,
        skipped=b.skipped_count, live_transactions=_vivos_do_lote(call, b),
    )


def _lotes_da_pessoa(call: ToolCall):
    me = call.identity.user_id
    espacos = {r.id: r.workspace.name for r in resolve.user_spaces(call.session, me)}
    base = select(ImportBatch).where(
        ImportBatch.created_by_user_id == me,
        (ImportBatch.workspace_id.in_(list(espacos) or [-1])) | (ImportBatch.kind == KIND_ACCOUNT),
    )
    return base, espacos


@tool(
    name="imports_list",
    title="Importações feitas",
    description=(
        "Lista os lotes de importação que VOCÊ fez (mais recentes primeiro): de despesas de um espaço "
        "ou de extrato de conta, com quanto entrou e quanto ainda existe. Com `batch_id`, traz as "
        "linhas do lote.\n"
        "Use quando: 'o que entrou na importação de ontem?', ou para achar o lote a desfazer "
        "(imports_undo).\n"
        "Não use quando: quiser importar um extrato novo (imports_preview → imports_commit)."
    ),
    input_model=ImportsListIn,
    output_model=ImportsListOut,
    scope=escopos.FINANCE_READ,
    kind="read",
    read_only=True,
    destructive=False,
    idempotent=True,
    cost=2,
    app_callable=True,
)
def imports_list(call: ToolCall) -> ToolOutput:
    from app.services import transaction_query

    a: ImportsListIn = call.args
    base, espacos = _lotes_da_pessoa(call)
    impressao = f"imp:{a.batch_id or '*'}"
    try:
        inicio = transaction_query.decode_cursor(a.cursor, impressao) if a.cursor else 0
    except transaction_query.InvalidCursor as exc:
        raise McpToolError(ErrorCode.VALIDATION_ERROR, str(exc))
    if a.batch_id is None:
        total = call.session.exec(select(func.count()).select_from(base.subquery())).one()
        lotes = call.session.exec(
            base.order_by(ImportBatch.created_at.desc(), ImportBatch.id.desc()).offset(inicio).limit(a.limit)
        ).all()
        saida = ImportsListOut(
            batches=[_lote_out(call, b, espacos) for b in lotes],
            next_cursor=transaction_query.encode_cursor(inicio + a.limit, impressao) if inicio + a.limit < total else None,
        )
        return ToolOutput(structured=saida, summary=f"{total} importação(ões).", entity_type="import", entity_ids=[b.id for b in lotes])
    lote = call.session.exec(base.where(ImportBatch.id == a.batch_id)).first()
    if lote is None:
        raise McpToolError(ErrorCode.NOT_FOUND, "Importação não encontrada.", details={"batch_id": a.batch_id})
    linhas_q = select(ImportRow).where(ImportRow.batch_id == lote.id)
    total = call.session.exec(select(func.count()).select_from(linhas_q.subquery())).one()
    linhas = call.session.exec(linhas_q.order_by(ImportRow.line, ImportRow.id).offset(inicio).limit(a.limit)).all()
    resumo = _lote_out(call, lote, espacos)
    saida = ImportsListOut(
        batches=[resumo],
        rows=[
            ImportRowOut(
                line=r.line, date=local_day(r.transaction_date), title=r.title, amount=r.amount,
                direction=r.direction, classification=r.classification,
                status=getattr(r.status, "value", r.status), transaction_id=r.transaction_id, reason=r.reason,
            )
            for r in linhas
        ],
        next_cursor=transaction_query.encode_cursor(inicio + a.limit, impressao) if inicio + a.limit < total else None,
    )
    return ToolOutput(
        structured=saida,
        summary=(
            f"Importação {lote.id} ({resumo.imported_on.strftime('%d/%m/%Y')}): {lote.imported_count} importada(s), "
            f"{resumo.live_transactions} ainda no app."
        ),
        entity_type="import",
        entity_ids=[lote.id],
        space_id=lote.workspace_id,
    )


# --- imports_undo --------------------------------------------------------------------------

class ImportsUndoIn(ToolInput):
    batch_id: int = Field(ge=1, description="O lote (imports_list).")
    confirmation_token: Optional[ConfirmationToken] = Field(
        None, description="Omitido: só a prévia (o que sai) e um token. Com o token da prévia: desfaz.",
    )


class ImportsUndoOut(BaseModel):
    batch_id: int
    mode: Literal["preview", "done"]
    will_undo: Dict[str, int] = Field(default_factory=dict, description="Na prévia: quanto de cada tipo sai.")
    undone: Dict[str, int] = Field(default_factory=dict, description="Feito: quanto de cada tipo saiu.")
    attachments: int = Field(0, description="Recibos que serão (ou foram) apagados para sempre.")
    confirmation_token: Optional[str] = None
    expires_at: Optional[dt.datetime] = None
    next_step: Optional[str] = None


def _o_que_sai(call: ToolCall, lote: ImportBatch) -> tuple[Dict[str, int], int, list[int]]:
    from app.models.attachment import Attachment

    if lote.kind == KIND_ACCOUNT:
        vivas = acc_imp._vivas(call.session, [lote.id])
        tipos: Dict[str, int] = {}
        for r in vivas:
            tipos[r.classification] = tipos.get(r.classification, 0) + 1
        txs = [r.transaction_id for r in vivas if r.transaction_id]
        ids = [r.id for r in vivas]
    else:
        txs = [t for _, t in call.session.exec(imp_cmd._vivos([lote.id])).all()]
        tipos = {"expense": len(txs)} if txs else {}
        ids = txs
    anexos = call.session.exec(
        select(func.count()).select_from(Attachment).where(Attachment.transaction_id.in_(txs))
    ).one() if txs else 0
    return tipos, int(anexos), ids


@tool(
    name="imports_undo",
    title="Desfazer importação",
    description=(
        "Desfaz um lote de importação (os dois modos), com as regras do app e tudo ou nada: exclui "
        "despesas e rendas, exclui transferências e estorna pagamentos de fatura que ele criou. Duas "
        "etapas: sem `confirmation_token` devolve o que sai (e os recibos apagados) e um token de 10 "
        "min; MOSTRE ao usuário e, com a confirmação dele, chame de novo com o token.\n"
        "Use quando: 'desfaça a importação de ontem' (o id vem de imports_list).\n"
        "Não use quando: for excluir só algumas linhas (transactions_bulk_preview)."
    ),
    input_model=ImportsUndoIn,
    output_model=ImportsUndoOut,
    scope=escopos.TRANSACTIONS_WRITE,
    kind="write",
    read_only=False,
    destructive=True,
    idempotent=True,
    cost=5,
    invoking="Desfazendo a importação…",
    invoked="Pronto",
    ui=WIDGET,
    app_callable=True,
    meta={"openai/widgetDescription": "O componente mostra o que sai e o botão de confirmar. Peça a confirmação ao usuário."},
)
def imports_undo(call: ToolCall) -> ToolOutput:
    a: ImportsUndoIn = call.args
    base, _ = _lotes_da_pessoa(call)
    lote = call.session.exec(base.where(ImportBatch.id == a.batch_id)).first()
    if lote is None:
        raise McpToolError(ErrorCode.NOT_FOUND, "Importação não encontrada.", details={"batch_id": a.batch_id})
    if lote.kind == KIND_ACCOUNT:
        _exige(call, escopos.ACCOUNTS_WRITE, "desfazer a importação de um extrato de conta")
    tipos, anexos, ids = _o_que_sai(call, lote)
    if a.confirmation_token is None:
        if not ids:
            saida = ImportsUndoOut(batch_id=lote.id, mode="preview")
            return ToolOutput(structured=saida, summary="Nada a desfazer: o que este lote criou já não existe.")
        token, expira = confirmation.issue(call, "imports_undo", ids, {"batch_id": lote.id})
        saida = ImportsUndoOut(
            batch_id=lote.id, mode="preview", will_undo=tipos, attachments=anexos,
            confirmation_token=token, expires_at=expira,
            next_step="Mostre ao usuário o que sai e, com a confirmação dele, chame imports_undo com este token.",
        )
        return ToolOutput(
            structured=saida,
            summary=(
                f"Desfazer a importação {lote.id} tira: " + ", ".join(f"{n} {t}" for t, n in sorted(tipos.items()))
                + (f"; {anexos} recibo(s) apagado(s) para sempre" if anexos else "") + ". Confirme com o usuário."
            ),
            entity_type="import",
            entity_ids=[lote.id],
        )
    registro = confirmation.consume(call, a.confirmation_token, "imports_undo")
    if registro.result is not None:
        saida = ImportsUndoOut(**registro.result)
        return ToolOutput(structured=saida, summary="Esta importação já tinha sido desfeita com este token.", replayed=True)
    if (registro.params or {}).get("batch_id") != lote.id or sorted(set(ids)) != list(registro.target_ids):
        raise McpToolError(
            ErrorCode.CONFLICT,
            "O lote mudou desde a prévia (algo foi excluído ou restaurado). Gere uma nova prévia com imports_undo.",
        )
    if lote.kind == KIND_ACCOUNT:
        resultado, liberar = acc_imp.undo_account_import(call.session, call.identity.user_id, lote.id, confirm_attachments=True)
        feitos = resultado["undone"]
    else:
        resultado, liberar = imp_cmd.undo_batch(
            call.session, lote.workspace_id, lote.id, membership_for_write(call, lote.workspace_id), confirm_attachments=True,
        )
        feitos = {"expense": resultado["deleted"]} if resultado["deleted"] else {}
    saida = ImportsUndoOut(batch_id=lote.id, mode="done", undone=feitos, attachments=resultado["attachments_removed"])
    confirmation.store_result(call, registro, saida.model_dump(mode="json"))
    return ToolOutput(
        structured=saida,
        summary=f"Importação {lote.id} desfeita: " + (", ".join(f"{n} {t}" for t, n in sorted(feitos.items())) or "nada") + ".",
        entity_type="import",
        entity_ids=[lote.id],
        after_commit=[lambda: free_keys(sorted(set(liberar)))] if liberar else [],
    )
