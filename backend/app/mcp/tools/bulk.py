"""Ações em MASSA com prévia e confirmação emitida pelo servidor.

Fluxo único para "apague as compras do McDonald's deste mês" e "categorize tudo
que está sem categoria em setembro como Alimentação":

1. `transactions_bulk_preview` — só leitura de dados: resolve o conjunto EXATO,
   separa o que não é elegível (pago, de outra pessoa, já categorizado), mostra
   total e amostra, e emite `confirmation_token` para os ids elegíveis.
2. O modelo MOSTRA a prévia ao usuário e pergunta.
3. `transactions_bulk_delete` / `transactions_bulk_categorize` recebem SÓ o token.

O token é o mecanismo de segurança (`app/mcp/confirmation.py`), não a frase "o
usuário confirmou". E a execução nunca alcança um id que não estava na prévia.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator
from sqlmodel import func, select

from app.core.config import settings
from app.domain.access_policy import can_write
from app.mcp import confirmation, resolve
from app.mcp.errors import ErrorCode, McpToolError
from app.mcp.money import fmt_brl
from app.mcp.registry import ToolCall, ToolInput, ToolOutput, tool
from app.mcp.schemas import MoneyTotal, Ref, TransactionBrief
from app.mcp.serializers import app_url, load_bundle, to_brief
from app.mcp.tools.transactions import WIDGET, SearchFilters, build_filters
from app.mcp.writes import ConfirmationToken, membership_for_write
from app.models.attachment import Attachment
from app.models.transaction import Transaction, TransactionItem, TransactionStatus
from app.models.workspace import WorkspaceRole, role_level
from app.schemas.transaction import BulkCategorizeRequest
from app.services import transaction_query
from app.services.attachment_storage import free_keys
from app.services.commands import transactions as tx_cmd
from app.services.oauth import scopes as escopos

AMOSTRA = 10
MAX_INELEGIVEIS = 20


class BulkPreviewIn(ToolInput):
    action: Literal["delete", "categorize"] = Field(description="O que fazer com o conjunto.")
    transaction_ids: Optional[List[int]] = Field(
        None, min_length=1, max_length=settings.MCP_BULK_MAX_ITEMS,
        description="Ids exatos (de transactions_search). Use isto OU `filters`.",
    )
    filters: Optional[SearchFilters] = Field(
        None, description="Os mesmos filtros de transactions_search (ao menos um). Use isto OU `transaction_ids`.",
    )
    category: Optional[str] = Field(None, max_length=120, description="Categoria a aplicar (action=categorize).")
    category_id: Optional[int] = None

    @model_validator(mode="after")
    def _alvo(self):
        if (self.transaction_ids is None) == (self.filters is None):
            raise ValueError("informe transaction_ids OU filters (exatamente um)")
        if self.filters is not None and not self.filters.model_dump(exclude_defaults=True):
            raise ValueError("filters precisa de ao menos um critério — não há ação em massa sobre tudo")
        if self.action == "categorize":
            if (self.category is None) == (self.category_id is None):
                raise ValueError("para categorizar, informe category OU category_id")
        elif self.category is not None or self.category_id is not None:
            raise ValueError("category só vale com action=categorize")
        return self


class Ineligible(BaseModel):
    id: int
    title: str
    reason: str


class BulkPreviewOut(BaseModel):
    action: str
    count: int = Field(description="Quantos lançamentos a ação alcançaria.")
    totals: List[MoneyTotal] = Field(description="Soma do valor cheio dos elegíveis, por moeda.")
    sample: List[TransactionBrief] = Field(description=f"Até {AMOSTRA} lançamentos do conjunto, para mostrar ao usuário.")
    ineligible_count: int
    ineligible: List[Ineligible] = Field(description="O que ficou de fora e por quê (até 20).")
    not_found_ids: List[int] = Field(default_factory=list, description="Ids pedidos que não existem ou não são visíveis.")
    attachments: int = Field(0, description="Anexos (recibos) que seriam apagados para sempre (action=delete).")
    category: Optional[Ref] = None
    space: Optional[Ref] = None
    confirmation_token: Optional[str] = Field(None, description="Passe para a tool de execução DEPOIS de o usuário confirmar.")
    expires_at: Optional[datetime] = None
    next_step: str


def _inelegivel(tx: Transaction, action: str, membership, categorizados: set[int]) -> Optional[str]:
    if membership is None or role_level(membership.role) < role_level(WorkspaceRole.member):
        return "seu papel neste espaço é somente leitura"
    if not can_write(tx.created_by_user_id, membership):
        return "lançamento de outra pessoa"
    if action == "delete" and tx.status == TransactionStatus.paid:
        return "marcado como pago (reabra antes)"
    if action == "categorize":
        if tx.status == TransactionStatus.cancelled:
            return "cancelado"
        if tx.id in categorizados:
            return "já tem categoria (use transactions_update para trocar)"
    return None


def _totais(txs: list[Transaction]) -> List[MoneyTotal]:
    soma: dict[str, list] = defaultdict(lambda: [Decimal("0"), 0])
    for t in txs:
        soma[t.currency][0] += t.total_amount
        soma[t.currency][1] += 1
    return [MoneyTotal(currency=m, amount=v, count=n) for m, (v, n) in sorted(soma.items())]


@tool(
    name="transactions_bulk_preview",
    title="Prévia de ação em massa",
    description=(
        "Primeiro passo OBRIGATÓRIO para excluir ou categorizar vários lançamentos (ou um lançamento "
        "com anexos). Não altera nada: calcula o conjunto exato, o total, uma amostra e o que ficou de "
        "fora, e devolve um `confirmation_token` válido por 10 minutos.\n"
        "Use quando: o usuário pedir para apagar/categorizar vários lançamentos (\"apague as compras "
        "do McDonald's deste mês\", \"categorize tudo sem categoria de setembro como Mercado\").\n"
        "Não use quando: for um único lançamento sem anexos (transactions_delete/transactions_update).\n"
        "Depois: MOSTRE count, total e amostra ao usuário e só com a confirmação dele chame "
        "transactions_bulk_delete ou transactions_bulk_categorize com o token. Categorizar só alcança "
        "lançamentos SEM categoria."
    ),
    input_model=BulkPreviewIn,
    output_model=BulkPreviewOut,
    scope=escopos.FINANCE_READ,
    kind="read",
    read_only=True,
    destructive=False,
    idempotent=True,
    cost=3,
    ui=WIDGET,
    invoking="Calculando a prévia…",
    invoked="Prévia pronta",
    meta={"openai/widgetDescription": (
        "O componente já mostra a prévia: quantos lançamentos, o total, uma amostra e o botão de "
        "confirmar. Não repita a lista; peça a confirmação ao usuário."
    )},
    examples=(
        {"action": "delete", "filters": {"text": "McDonald's", "month": "2026-09"}},
        {"action": "categorize", "filters": {"uncategorized": True, "month": "2026-09"}, "category": "Mercado"},
    ),
)
def transactions_bulk_preview(call: ToolCall) -> ToolOutput:
    a: BulkPreviewIn = call.args
    me = call.identity.user_id
    teto = settings.MCP_BULK_MAX_ITEMS
    if a.filters is not None:
        memberships, filtros, _ = build_filters(call, a.filters)
    else:
        memberships = [r.membership for r in resolve.user_spaces(call.session, me)]
        filtros = transaction_query.TxFilters(ids=tuple(a.transaction_ids))
    consulta = transaction_query.build_statement(memberships, filtros).order_by(
        Transaction.transaction_date.desc(), Transaction.id.desc()
    )
    txs = list(call.session.exec(consulta.limit(teto + 1)).all())
    if len(txs) > teto:
        raise McpToolError(
            ErrorCode.VALIDATION_ERROR,
            f"O conjunto passa de {teto} lançamentos. Restrinja os filtros (período, espaço, cartão, texto).",
            details={"max_items": teto},
        )
    nao_achados = sorted(set(a.transaction_ids or []) - {t.id for t in txs})

    por_espaco = {m.workspace_id: m for m in memberships}
    categorizados: set[int] = set()
    if a.action == "categorize" and txs:
        categorizados = set(call.session.exec(
            select(TransactionItem.transaction_id).where(
                TransactionItem.transaction_id.in_([t.id for t in txs]),
                TransactionItem.category_id.is_not(None),
            )
        ).all())
    elegiveis, fora = [], []
    for t in txs:
        motivo = _inelegivel(t, a.action, por_espaco.get(t.workspace_id), categorizados)
        (fora if motivo else elegiveis).append((t, motivo))

    categoria = espaco = None
    if a.action == "categorize" and elegiveis:
        espacos = {t.workspace_id for t, _ in elegiveis}
        if len(espacos) > 1:
            raise McpToolError(
                ErrorCode.VALIDATION_ERROR,
                "Os lançamentos estão em mais de um espaço, e cada espaço tem as próprias categorias. "
                "Restrinja com filters.space e faça uma prévia por espaço.",
                details={"space_ids": sorted(espacos)},
            )
        ws_id = espacos.pop()
        cat = resolve.resolve_category(call.session, ws_id, category_id=a.category_id, category=a.category)
        categoria = Ref(id=cat.id, name=cat.name)
        ref = next(r for r in resolve.user_spaces(call.session, me) if r.id == ws_id)
        espaco = Ref(id=ws_id, name=ref.workspace.name)

    so_txs = [t for t, _ in elegiveis]
    pacote = load_bundle(call.session, so_txs[:AMOSTRA])
    anexos = 0
    if a.action == "delete" and so_txs:
        anexos = int(call.session.exec(
            select(func.count()).select_from(Attachment).where(Attachment.transaction_id.in_([t.id for t in so_txs]))
        ).one())

    token = expira = None
    if so_txs:
        acao = "bulk_delete" if a.action == "delete" else "bulk_categorize"
        params = {"category_id": categoria.id, "space_id": espaco.id} if categoria else {}
        token, expira = confirmation.issue(call, acao, [t.id for t in so_txs], params)
        proximo = (
            "Mostre a prévia ao usuário. Só depois da confirmação dele chame "
            + ("transactions_bulk_delete" if a.action == "delete" else "transactions_bulk_categorize")
            + " com o confirmation_token (vale 10 minutos, uma vez)."
        )
    else:
        proximo = "Nada a fazer: nenhum lançamento elegível. Explique ao usuário o motivo (ver `ineligible`)."

    saida = BulkPreviewOut(
        action=a.action,
        count=len(so_txs),
        totals=_totais(so_txs),
        sample=[to_brief(t, pacote, me) for t in so_txs[:AMOSTRA]],
        ineligible_count=len(fora),
        ineligible=[Ineligible(id=t.id, title=t.title, reason=m) for t, m in fora[:MAX_INELEGIVEIS]],
        not_found_ids=nao_achados,
        attachments=anexos,
        category=categoria,
        space=espaco,
        confirmation_token=token,
        expires_at=expira,
        next_step=proximo,
    )
    verbo = "excluir" if a.action == "delete" else f"categorizar como {categoria.name}" if categoria else "categorizar"
    total_txt = "; ".join(fmt_brl(t.amount, t.currency) for t in saida.totals) or "nada"
    resumo = f"Prévia: {verbo} {saida.count} lançamento(s), total {total_txt}."
    if anexos:
        resumo += f" ATENÇÃO: {anexos} anexo(s) seriam apagados para sempre."
    if fora:
        resumo += f" {len(fora)} ficaram de fora."
    return ToolOutput(
        structured=saida,
        summary=resumo + " " + proximo,
        entity_type="transaction",
        entity_ids=[t.id for t in so_txs],
        widget={"view": "bulk_preview", "app_url": app_url("/transactions")},
    )


# --- Execução ---------------------------------------------------------------------

class BulkExecIn(ToolInput):
    confirmation_token: ConfirmationToken


class BulkResult(BaseModel):
    action: str
    count: int = Field(description="Quantos lançamentos foram alterados.")
    transaction_ids: List[int]
    skipped: int = Field(0, description="Pulados na execução (categorizar: já tinham categoria).")
    attachments_removed: int = 0
    replayed: bool = Field(False, description="true = este token já tinha sido executado; nada foi feito de novo.")


def _replay(call: ToolCall, registro, acao: str) -> ToolOutput:
    saida = BulkResult(**{**registro.result, "replayed": True})
    return ToolOutput(
        structured=saida,
        summary="Esta confirmação já tinha sido executada; nada foi feito de novo.",
        entity_type="transaction",
        entity_ids=saida.transaction_ids,
        replayed=True,
    )


def _alvos(call: ToolCall, ids: list[int]) -> list[Transaction]:
    return list(call.session.exec(select(Transaction).where(Transaction.id.in_(ids))).all())


@tool(
    name="transactions_bulk_delete",
    title="Excluir em massa (confirmado)",
    description=(
        "Executa a exclusão preparada por transactions_bulk_preview (action=delete). Recebe só o "
        "`confirmation_token`: exclui exatamente o conjunto da prévia, tudo ou nada. Se algo mudou "
        "desde a prévia (lançamento pago, apagado, fora do seu alcance), nada é excluído e é preciso "
        "nova prévia. Anexos dos excluídos são apagados para sempre; os lançamentos podem ser "
        "restaurados um a um com transactions_restore.\n"
        "Use quando: o usuário CONFIRMOU a prévia que você mostrou.\n"
        "Não use quando: não houver prévia confirmada pelo usuário nesta conversa."
    ),
    input_model=BulkExecIn,
    output_model=BulkResult,
    scope=escopos.TRANSACTIONS_WRITE,
    kind="destructive",
    read_only=False,
    destructive=True,
    idempotent=True,
    cost=5,
    app_callable=True,
    invoking="Excluindo…",
    invoked="Exclusão concluída",
    examples=({"confirmation_token": "cfm_cf_…"},),
)
def transactions_bulk_delete(call: ToolCall) -> ToolOutput:
    registro = confirmation.consume(call, call.args.confirmation_token, "bulk_delete")
    if registro.result is not None:
        return _replay(call, registro, "delete")
    ids = list(registro.target_ids)
    txs = _alvos(call, ids)
    memberships: dict[int, object] = {}
    mudou = len(txs) != len(ids)
    for t in txs:
        if t.workspace_id not in memberships:
            try:
                memberships[t.workspace_id] = membership_for_write(call, t.workspace_id)
            except McpToolError:
                memberships[t.workspace_id] = None
        m = memberships[t.workspace_id]
        if t.deleted_at is not None or m is None or _inelegivel(t, "delete", m, set()):
            mudou = True
    if mudou:
        raise McpToolError(
            ErrorCode.CONFLICT,
            "O conjunto mudou desde a prévia (algum lançamento foi pago, excluído ou saiu do seu alcance). "
            "Nada foi excluído. Gere uma nova prévia com transactions_bulk_preview.",
        )
    anexos = int(call.session.exec(
        select(func.count()).select_from(Attachment).where(Attachment.transaction_id.in_(ids))
    ).one())
    liberar: list[str] = []
    for t in txs:
        _, chaves = tx_cmd.delete_transaction(call.session, t.workspace_id, t.id, memberships[t.workspace_id])
        liberar.extend(chaves)
    resultado = {"action": "delete", "count": len(ids), "transaction_ids": ids, "skipped": 0, "attachments_removed": anexos}
    confirmation.store_result(call, registro, resultado)
    total = sum((t.total_amount for t in txs), Decimal("0"))
    return ToolOutput(
        structured=BulkResult(**resultado),
        summary=f"Excluídos {len(ids)} lançamento(s) ({fmt_brl(total)}). Dá para restaurar um a um com transactions_restore.",
        entity_type="transaction",
        entity_ids=ids,
        after_commit=[lambda: free_keys(sorted(set(liberar)))] if liberar else [],
    )


@tool(
    name="transactions_bulk_categorize",
    title="Categorizar em massa (confirmado)",
    description=(
        "Executa a categorização preparada por transactions_bulk_preview (action=categorize). "
        "Recebe só o `confirmation_token` e aplica a categoria da prévia aos lançamentos da prévia "
        "que continuam sem categoria.\n"
        "Use quando: o usuário CONFIRMOU a prévia que você mostrou.\n"
        "Não use quando: não houver prévia confirmada; para trocar a categoria de um lançamento "
        "específico use transactions_update."
    ),
    input_model=BulkExecIn,
    output_model=BulkResult,
    scope=escopos.TRANSACTIONS_WRITE,
    kind="write",
    read_only=False,
    destructive=True,
    idempotent=True,
    cost=5,
    app_callable=True,
    invoking="Categorizando…",
    invoked="Categorização concluída",
    examples=({"confirmation_token": "cfm_cf_…"},),
)
def transactions_bulk_categorize(call: ToolCall) -> ToolOutput:
    registro = confirmation.consume(call, call.args.confirmation_token, "bulk_categorize")
    if registro.result is not None:
        return _replay(call, registro, "categorize")
    params = registro.params or {}
    ws_id = int(params["space_id"])
    membership = membership_for_write(call, ws_id)
    ids = list(registro.target_ids)
    feito = tx_cmd.bulk_categorize(
        call.session, ws_id, BulkCategorizeRequest(transaction_ids=ids, category_id=int(params["category_id"])), membership
    )
    atualizados = int(feito.get("updated", 0))
    pulados = len(ids) - atualizados
    resultado = {"action": "categorize", "count": atualizados, "transaction_ids": ids, "skipped": pulados, "attachments_removed": 0}
    confirmation.store_result(call, registro, resultado)
    resumo = f"Categorizados {atualizados} lançamento(s)."
    if pulados:
        resumo += f" {pulados} pulado(s) (ganharam categoria ou saíram do seu alcance desde a prévia)."
    return ToolOutput(
        structured=BulkResult(**resultado),
        summary=resumo,
        entity_type="transaction",
        entity_ids=ids,
        space_id=ws_id,
    )
