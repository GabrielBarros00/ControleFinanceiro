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
from app.models.tag import TransactionTagLink
from app.models.transaction import SplitMode, Transaction, TransactionItem, TransactionStatus
from app.models.workspace import WorkspaceRole, role_level
from app.schemas.transaction import BulkCategorizeRequest, TransactionUpdate
from app.services import transaction_query
from app.services.attachment_storage import free_keys
from app.services.commands import transactions as tx_cmd
from app.services.oauth import scopes as escopos

AMOSTRA = 10
MAX_INELEGIVEIS = 20


_ACOES_DE_EDICAO = ("recategorize", "tag", "untag", "settle")


class BulkPreviewIn(ToolInput):
    action: Literal["delete", "categorize", "recategorize", "tag", "untag", "settle"] = Field(
        description=(
            "delete = excluir; categorize = pôr categoria nos SEM categoria; recategorize = trocar a "
            "categoria; tag / untag = pôr/tirar uma tag; settle = marcar como pago."
        ),
    )
    transaction_ids: Optional[List[int]] = Field(
        None, min_length=1, max_length=settings.MCP_BULK_MAX_ITEMS,
        description="Ids exatos (de transactions_search). Use isto OU `filters`.",
    )
    filters: Optional[SearchFilters] = Field(
        None, description="Os mesmos filtros de transactions_search (ao menos um). Use isto OU `transaction_ids`.",
    )
    category: Optional[str] = Field(None, max_length=120, description="Categoria a aplicar (categorize/recategorize).")
    category_id: Optional[int] = None
    tag: Optional[str] = Field(None, max_length=60, description="Tag a pôr ou tirar (tag/untag).")

    @model_validator(mode="after")
    def _alvo(self):
        if (self.transaction_ids is None) == (self.filters is None):
            raise ValueError("informe transaction_ids OU filters (exatamente um)")
        if self.filters is not None and not self.filters.model_dump(exclude_defaults=True):
            raise ValueError("filters precisa de ao menos um critério — não há ação em massa sobre tudo")
        if self.action in ("categorize", "recategorize"):
            if (self.category is None) == (self.category_id is None):
                raise ValueError("para categorizar, informe category OU category_id")
        elif self.category is not None or self.category_id is not None:
            raise ValueError("category só vale com action=categorize ou recategorize")
        if self.action in ("tag", "untag"):
            if not self.tag:
                raise ValueError("informe a tag")
        elif self.tag is not None:
            raise ValueError("tag só vale com action=tag ou untag")
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
    tag: Optional[Ref] = None
    space: Optional[Ref] = None
    confirmation_token: Optional[str] = Field(None, description="Passe para a tool de execução DEPOIS de o usuário confirmar.")
    expires_at: Optional[datetime] = None
    next_step: str


def _inelegivel(
    tx: Transaction, action: str, membership, categorizados: set[int], *,
    detalhados: frozenset | set = frozenset(), tags: Optional[dict] = None, tag_id: Optional[int] = None,
) -> Optional[str]:
    if membership is None or role_level(membership.role) < role_level(WorkspaceRole.member):
        return "seu papel neste espaço é somente leitura"
    if not can_write(tx.created_by_user_id, membership):
        return "lançamento de outra pessoa"
    if action in ("delete",) + _ACOES_DE_EDICAO and tx.status == TransactionStatus.paid:
        return "marcado como pago (reabra antes)"
    if action in ("categorize", "recategorize", "settle") and tx.status == TransactionStatus.cancelled:
        return "cancelado"
    if action == "categorize" and tx.id in categorizados:
        return "já tem categoria (use recategorize para trocar)"
    if action == "recategorize" and tx.id in detalhados:
        return "tem itens com categorias próprias (edite um a um)"
    if action == "tag" and tag_id is not None and tag_id in (tags or {}).get(tx.id, set()):
        return "já tem a tag"
    if action == "untag" and tag_id is not None and tag_id not in (tags or {}).get(tx.id, set()):
        return "não tem a tag"
    if action == "settle":
        if tx.credit_card_id:
            return "compra no cartão se paga pela fatura"
        if tx.settled_at is not None:
            return "já está paga"
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
        "Primeiro passo OBRIGATÓRIO para alterar vários lançamentos (ou excluir um com anexos): "
        "excluir, categorizar os sem categoria, trocar categoria, pôr/tirar tag, marcar como pago — ou "
        "DESFAZER UMA IMPORTAÇÃO (action=delete com filters.import_batch_id). Não altera nada: calcula "
        "o conjunto exato, o total, uma amostra e o que ficou de fora, e devolve um `confirmation_token` "
        "válido por 10 minutos.\n"
        "Use quando: \"apague as compras do McDonald's deste mês\", \"categorize tudo sem categoria de "
        "setembro como Mercado\", \"ponha a tag viagem nas compras de julho\".\n"
        "Não use quando: for um único lançamento sem anexos (transactions_delete/transactions_update).\n"
        "Depois: MOSTRE count, total e amostra ao usuário e só com a confirmação dele chame a tool que "
        "`next_step` indicar (bulk_delete, bulk_categorize ou bulk_update) com o token."
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
    # O componente pede a prévia ao selecionar linhas e no "Desfazer importação".
    app_callable=True,
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
    categorizados, detalhados, tags_de = _estado_para_elegibilidade(call, txs)

    # Tag e categoria são do espaço: com ação que usa uma delas, o conjunto tem de
    # estar num espaço só (resolvido ANTES da elegibilidade, que depende da tag).
    categoria = espaco = etiqueta = None
    alvo_tag_id = None
    if a.action in ("tag", "untag") and txs:
        espacos_tag = {t.workspace_id for t in txs}
        if len(espacos_tag) > 1:
            raise McpToolError(
                ErrorCode.VALIDATION_ERROR,
                "Os lançamentos estão em mais de um espaço, e cada espaço tem as próprias tags. "
                "Restrinja com filters.space e faça uma prévia por espaço.",
                details={"space_ids": sorted(espacos_tag)},
            )
        ws_tag = next(iter(espacos_tag))
        alvo_tag_id = resolve.resolve_tags(call.session, ws_tag, [a.tag])[0]
    elegiveis, fora = [], []
    for t in txs:
        motivo = _inelegivel(
            t, a.action, por_espaco.get(t.workspace_id), categorizados,
            detalhados=detalhados, tags=tags_de, tag_id=alvo_tag_id,
        )
        (fora if motivo else elegiveis).append((t, motivo))

    if a.action in ("categorize", "recategorize", "tag", "untag", "settle") and elegiveis:
        espacos = {t.workspace_id for t, _ in elegiveis}
        if len(espacos) > 1:
            raise McpToolError(
                ErrorCode.VALIDATION_ERROR,
                "Os lançamentos estão em mais de um espaço, e cada espaço tem as próprias categorias. "
                "Restrinja com filters.space e faça uma prévia por espaço.",
                details={"space_ids": sorted(espacos)},
            )
        ws_id = espacos.pop()
        if a.action in ("categorize", "recategorize"):
            cat = resolve.resolve_category(call.session, ws_id, category_id=a.category_id, category=a.category)
            categoria = Ref(id=cat.id, name=cat.name)
        if alvo_tag_id is not None:
            nome_tag = next(t.name for t in resolve.space_tags(call.session, ws_id) if t.id == alvo_tag_id)
            etiqueta = Ref(id=alvo_tag_id, name=nome_tag)
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
        executora = {
            "delete": ("bulk_delete", "transactions_bulk_delete"),
            "categorize": ("bulk_categorize", "transactions_bulk_categorize"),
        }.get(a.action, ("bulk_update", "transactions_bulk_update"))
        params: dict = {}
        if a.action == "categorize":
            params = {"category_id": categoria.id, "space_id": espaco.id}
        elif a.action in _ACOES_DE_EDICAO:
            params = {"action": a.action, "space_id": espaco.id}
            if categoria:
                params["category_id"] = categoria.id
            if etiqueta:
                params["tag_id"] = etiqueta.id
        token, expira = confirmation.issue(call, executora[0], [t.id for t in so_txs], params)
        proximo = (
            "Mostre a prévia ao usuário. Só depois da confirmação dele chame "
            + executora[1] + " com o confirmation_token (vale 10 minutos, uma vez)."
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
        tag=etiqueta,
        space=espaco,
        confirmation_token=token,
        expires_at=expira,
        next_step=proximo,
    )
    verbo = {
        "delete": "excluir",
        "categorize": f"categorizar como {categoria.name}" if categoria else "categorizar",
        "recategorize": f"mudar a categoria para {categoria.name}" if categoria else "recategorizar",
        "tag": f"pôr a tag {etiqueta.name}" if etiqueta else "pôr a tag",
        "untag": f"tirar a tag {etiqueta.name}" if etiqueta else "tirar a tag",
        "settle": "marcar como pago",
    }[a.action]
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
    ui=WIDGET,
    meta={"openai/widgetDescription": "O componente mostra o resultado com as ações possíveis (desfazer, editar). Confirme em uma frase, sem repetir os números."},
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
    ui=WIDGET,
    meta={"openai/widgetDescription": "O componente mostra o resultado com as ações possíveis (desfazer, editar). Confirme em uma frase, sem repetir os números."},
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


# --- transactions_bulk_update ---------------------------------------------------------

def _estado_para_elegibilidade(call: ToolCall, txs: list[Transaction]) -> tuple[set[int], set[int], dict[int, set[int]]]:
    """(com categoria, detalhados por item, tags de cada um) — o que decide quem entra."""
    ids = [t.id for t in txs]
    if not ids:
        return set(), set(), {}
    categorizados = set(call.session.exec(
        select(TransactionItem.transaction_id).where(
            TransactionItem.transaction_id.in_(ids), TransactionItem.category_id.is_not(None),
        )
    ).all())
    contagem = dict(call.session.exec(
        select(TransactionItem.transaction_id, func.count())
        .where(TransactionItem.transaction_id.in_(ids)).group_by(TransactionItem.transaction_id)
    ).all())
    detalhados = {t.id for t in txs if t.split_mode == SplitMode.item or contagem.get(t.id, 0) > 1}
    tags: dict[int, set[int]] = defaultdict(set)
    for tx_id, tag_id in call.session.exec(
        select(TransactionTagLink.transaction_id, TransactionTagLink.tag_id).where(TransactionTagLink.transaction_id.in_(ids))
    ).all():
        tags[tx_id].add(tag_id)
    return categorizados, detalhados, tags


@tool(
    name="transactions_bulk_update",
    title="Alterar em massa (confirmado)",
    description=(
        "Executa a alteração preparada por transactions_bulk_preview com action recategorize (troca a "
        "categoria), tag / untag (põe ou tira uma tag) ou settle (marca como pago). Recebe só o "
        "`confirmation_token` e altera exatamente o conjunto da prévia, tudo ou nada; se algo mudou "
        "desde a prévia, nada é alterado e é preciso nova prévia.\n"
        "Use quando: o usuário CONFIRMOU a prévia que você mostrou.\n"
        "Não use quando: não houver prévia confirmada; para excluir (transactions_bulk_delete) ou "
        "categorizar só os sem categoria (transactions_bulk_categorize)."
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
    invoking="Aplicando…",
    invoked="Alteração concluída",
    examples=({"confirmation_token": "cfm_cf_…"},),
    ui=WIDGET,
    meta={"openai/widgetDescription": "O componente mostra o resultado com as ações possíveis (desfazer, editar). Confirme em uma frase, sem repetir os números."},
)
def transactions_bulk_update(call: ToolCall) -> ToolOutput:
    registro = confirmation.consume(call, call.args.confirmation_token, "bulk_update")
    if registro.result is not None:
        return _replay(call, registro, "update")
    params = registro.params or {}
    acao = params["action"]
    ws_id = int(params["space_id"])
    membership = membership_for_write(call, ws_id)
    ids = list(registro.target_ids)
    txs = _alvos(call, ids)
    categorizados, detalhados, tags = _estado_para_elegibilidade(call, txs)
    tag_id = params.get("tag_id")
    if len(txs) != len(ids) or any(
        t.deleted_at is not None or t.workspace_id != ws_id
        or _inelegivel(t, acao, membership, categorizados, detalhados=detalhados, tags=tags, tag_id=tag_id)
        for t in txs
    ):
        raise McpToolError(
            ErrorCode.CONFLICT,
            "O conjunto mudou desde a prévia (algum lançamento foi pago, excluído, alterado ou saiu do seu "
            "alcance). Nada foi alterado. Gere uma nova prévia com transactions_bulk_preview.",
        )
    for t in txs:
        if acao == "recategorize":
            entrada = TransactionUpdate(category_id=int(params["category_id"]))
        elif acao == "tag":
            entrada = TransactionUpdate(tag_ids=sorted(tags.get(t.id, set()) | {int(tag_id)}))
        elif acao == "untag":
            entrada = TransactionUpdate(tag_ids=sorted(tags.get(t.id, set()) - {int(tag_id)}))
        else:
            entrada = TransactionUpdate(settled=True)
        tx_cmd.update_transaction(call.session, ws_id, t.id, entrada, membership)
    resultado = {"action": acao, "count": len(ids), "transaction_ids": ids, "skipped": 0, "attachments_removed": 0}
    confirmation.store_result(call, registro, resultado)
    verbo = {"recategorize": "Recategorizados", "tag": "Marcados com a tag", "untag": "Tag removida de", "settle": "Marcados como pagos"}[acao]
    return ToolOutput(
        structured=BulkResult(**resultado),
        summary=f"{verbo}: {len(ids)} lançamento(s).",
        entity_type="transaction",
        entity_ids=ids,
        space_id=ws_id,
    )
