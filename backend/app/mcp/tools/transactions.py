"""Consulta de lançamentos: `transactions_search` e `transactions_get`."""
from __future__ import annotations

from typing import List, Literal, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlmodel import select

from app.api.deps import get_workspace_membership
from app.domain.access_policy import get_visible_transaction
from app.mcp import resolve
from app.mcp.dates import CivilDate, MonthKey
from app.mcp.errors import ErrorCode, McpToolError
from app.mcp.money import MoneyInOrZero, fmt_brl
from app.mcp.registry import ToolCall, ToolInput, ToolOutput, tool
from app.mcp.schemas import MoneyTotal, Ref, TransactionBrief, TransactionOut
from app.mcp.serializers import load_bundle, one, to_brief
from app.models.transaction import Transaction
from app.services import transaction_query
from app.services.oauth import scopes as escopos

WIDGET = "ui://controle-financeiro/widget-v1.html"

PaymentMethodIn = Literal["credit_card", "debit_card", "pix", "cash", "bank_transfer", "boleto", "other"]
StatusIn = Literal["draft", "pending", "confirmed", "paid", "cancelled"]


class SearchFilters(ToolInput):
    """Filtros de domínio — nunca SQL. Todos opcionais e combináveis (E lógico)."""

    space: Optional[str] = Field(None, max_length=120, description="Restringe a um espaço (nome).")
    space_id: Optional[int] = None
    text: Optional[str] = Field(None, min_length=1, max_length=80, description="Trecho do título ou da descrição.")
    date_from: Optional[CivilDate] = Field(None, description="Data da compra a partir de (inclusive).")
    date_to: Optional[CivilDate] = Field(None, description="Data da compra até (inclusive).")
    month: Optional[MonthKey] = Field(None, description="Competência (mês do gasto), YYYY-MM.")
    card: Optional[str] = Field(None, max_length=120, description="Nome do cartão de crédito.")
    card_id: Optional[int] = None
    account: Optional[str] = Field(None, max_length=120, description="Conta de onde saiu o dinheiro.")
    account_id: Optional[int] = None
    category: Optional[str] = Field(None, max_length=120)
    category_id: Optional[int] = None
    uncategorized: bool = Field(False, description="Só lançamentos sem categoria.")
    tag: Optional[str] = Field(None, max_length=60)
    person: Optional[str] = Field(None, max_length=120, description="Pessoa envolvida (pagou ou divide).")
    person_id: Optional[int] = None
    payment_method: Optional[PaymentMethodIn] = None
    status: Optional[List[StatusIn]] = Field(None, max_length=5)
    settled: Optional[bool] = Field(None, description="true = já pago; false = a pagar (fora do cartão).")
    min_amount: Optional[MoneyInOrZero] = None
    max_amount: Optional[MoneyInOrZero] = None
    installment_group_id: Optional[str] = Field(None, max_length=64, description="Parcelas de uma mesma compra.")

    @model_validator(mode="after")
    def _periodo(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from deve ser anterior ou igual a date_to")
        if self.min_amount is not None and self.max_amount is not None and self.min_amount > self.max_amount:
            raise ValueError("min_amount deve ser menor ou igual a max_amount")
        return self


class ResolvedFilters(BaseModel):
    space: Optional[Ref] = None
    card: Optional[Ref] = None
    account: Optional[Ref] = None
    person: Optional[Ref] = None
    category_ids: Optional[List[int]] = None
    tag_ids: Optional[List[int]] = None


def build_filters(call: ToolCall, f: SearchFilters):
    """Resolve os nomes e monta os filtros + os memberships que entram na busca."""
    me = call.identity.user_id
    espacos = resolve.user_spaces(call.session, me)
    alvo = resolve.resolve_space(call.session, me, space_id=f.space_id, space=f.space)
    if alvo is not None:
        espacos = [alvo]
    cartao = resolve.resolve_card(call.session, me, card_id=f.card_id, card=f.card)
    # Conta inativa ainda tem histórico: na BUSCA ela vale (na escrita, não).
    conta = resolve.resolve_account(
        call.session, me, account_id=f.account_id, account=f.account, include_inactive=True
    )
    pessoa_id = resolve.person_any(call.session, espacos, me, person_id=f.person_id, person=f.person)
    categorias = resolve.categories_any(call.session, espacos, category_id=f.category_id, category=f.category)
    tags = resolve.tags_any(call.session, espacos, tag=f.tag)
    filtros = transaction_query.TxFilters(
        date_from=f.date_from,
        date_to=f.date_to,
        month=f.month,
        text=f.text,
        card_id=cartao.id if cartao else None,
        account_id=conta.id if conta else None,
        category_ids=categorias,
        tag_ids=tags,
        person_id=pessoa_id,
        payment_method=f.payment_method,
        statuses=tuple(f.status or ()),
        settled=f.settled,
        min_amount=f.min_amount,
        max_amount=f.max_amount,
        installment_group_id=f.installment_group_id,
        uncategorized=f.uncategorized,
    )
    nomes = {}
    if pessoa_id is not None:
        for r in espacos:
            for m in resolve.space_members(call.session, r.id):
                nomes.setdefault(m.id, m.name)
    resolvido = ResolvedFilters(
        space=Ref(id=alvo.id, name=alvo.workspace.name) if alvo else None,
        card=Ref(id=cartao.id, name=cartao.name) if cartao else None,
        account=Ref(id=conta.id, name=conta.name) if conta else None,
        person=Ref(id=pessoa_id, name=nomes.get(pessoa_id, "?")) if pessoa_id is not None else None,
        category_ids=categorias,
        tag_ids=tags,
    )
    return [r.membership for r in espacos], filtros, resolvido


class SearchIn(SearchFilters):
    sort: Literal["date_desc", "date_asc", "amount_desc", "amount_asc"] = "date_desc"
    limit: int = Field(20, ge=1, le=transaction_query.MAX_LIMIT)
    cursor: Optional[str] = Field(None, max_length=512, description="`next_cursor` da página anterior.")


class SearchOut(BaseModel):
    items: List[TransactionBrief]
    total_count: int = Field(description="Quantos lançamentos o filtro encontrou (todas as páginas).")
    totals: List[MoneyTotal] = Field(description="Soma do valor cheio, por moeda (só status realizados).")
    my_share_totals: List[MoneyTotal] = Field(description="Soma da SUA parte, por moeda (só status realizados).")
    next_cursor: Optional[str] = None
    resolved: ResolvedFilters


@tool(
    name="transactions_search",
    title="Buscar lançamentos",
    description=(
        "Busca lançamentos (despesas) em todos os seus espaços por período, texto, cartão, conta, "
        "categoria, tag, pessoa, valor, forma de pagamento e situação. Devolve a lista paginada "
        "(com `id`), o total do filtro inteiro e a SUA parte.\n"
        "Use quando: precisar achar um lançamento para ver, editar ou excluir ('a compra do "
        "McDonald's de ontem'), ou responder 'quanto gastei com X' por período ou filtro.\n"
        "Não use quando: quiser o resumo do mês por categoria (reports_summary) ou a fatura de um "
        "cartão (statements_get). Datas: YYYY-MM-DD; `month` filtra por competência."
    ),
    input_model=SearchIn,
    output_model=SearchOut,
    scope=escopos.FINANCE_READ,
    kind="read",
    read_only=True,
    destructive=False,
    idempotent=True,
    cost=2,
)
def transactions_search(call: ToolCall) -> ToolOutput:
    a: SearchIn = call.args
    memberships, filtros, resolvido = build_filters(call, a)
    try:
        pagina = transaction_query.search(
            call.session, memberships, filtros,
            me_id=call.identity.user_id, limit=a.limit, cursor=a.cursor, sort=a.sort,
        )
    except transaction_query.InvalidCursor as exc:
        raise McpToolError(ErrorCode.VALIDATION_ERROR, str(exc))
    pacote = load_bundle(call.session, pagina.items)
    saida = SearchOut(
        items=[to_brief(t, pacote, call.identity.user_id) for t in pagina.items],
        total_count=pagina.total_count,
        totals=[MoneyTotal(**t) for t in pagina.totals],
        my_share_totals=[MoneyTotal(**t) for t in pagina.my_share_totals],
        next_cursor=pagina.next_cursor,
        resolved=resolvido,
    )
    resumo = f"{pagina.total_count} lançamento(s) encontrado(s)"
    if pagina.totals:
        resumo += "; total " + ", ".join(fmt_brl(t["amount"], t["currency"]) for t in pagina.totals)
    if pagina.my_share_totals:
        resumo += "; sua parte " + ", ".join(fmt_brl(t["amount"], t["currency"]) for t in pagina.my_share_totals)
    return ToolOutput(
        structured=saida,
        summary=resumo + ".",
        entity_type="transaction",
        entity_ids=[t.id for t in pagina.items],
    )


# --- transactions_get ----------------------------------------------------------------

class GetIn(ToolInput):
    transaction_id: int = Field(ge=1)


def visible_transaction(call: ToolCall, transaction_id: int, *, include_deleted: bool = False) -> Transaction:
    """O lançamento, se ESTA pessoa pode vê-lo; senão NOT_FOUND (nunca "sem permissão").

    O espaço vem da própria linha; a visibilidade, do membership da pessoa nele e
    do `get_visible_transaction` — o mesmo gate do REST. Um id de outra pessoa (ou
    de um espaço de que ela não participa) é indistinguível de um id inexistente.
    """
    ws_id = call.session.exec(select(Transaction.workspace_id).where(Transaction.id == transaction_id)).first()
    if ws_id is None:
        raise McpToolError(ErrorCode.NOT_FOUND, "Lançamento não encontrado.", details={"transaction_id": transaction_id})
    try:
        membership = get_workspace_membership(ws_id, session=call.session, current_user=call.user)
    except HTTPException:
        raise McpToolError(ErrorCode.NOT_FOUND, "Lançamento não encontrado.", details={"transaction_id": transaction_id})
    if include_deleted:
        from app.domain.access_policy import scope_transactions

        tx = call.session.exec(scope_transactions(
            select(Transaction).where(Transaction.id == transaction_id, Transaction.workspace_id == ws_id),
            membership,
        )).first()
        if tx is None:
            raise McpToolError(ErrorCode.NOT_FOUND, "Lançamento não encontrado.", details={"transaction_id": transaction_id})
        return tx
    return get_visible_transaction(call.session, ws_id, transaction_id, membership)


class TransactionResult(BaseModel):
    transaction: TransactionOut


@tool(
    name="transactions_get",
    title="Ver lançamento",
    description=(
        "Mostra um lançamento completo pelo `transaction_id`: valor, data, espaço, quem pagou, "
        "como foi dividido (a parte de cada pessoa), categoria, tags, cartão/fatura, parcelas e "
        "moeda original.\n"
        "Use quando: já tiver o id (de transactions_search ou de uma criação) e precisar dos "
        "detalhes antes de explicar ou editar.\n"
        "Não use quando: ainda não souber o id — busque com transactions_search."
    ),
    input_model=GetIn,
    output_model=TransactionResult,
    scope=escopos.FINANCE_READ,
    kind="read",
    read_only=True,
    destructive=False,
    idempotent=True,
    ui=WIDGET,
    invoking="Abrindo o lançamento…",
    invoked="Lançamento aberto",
)
def transactions_get(call: ToolCall) -> ToolOutput:
    tx = visible_transaction(call, call.args.transaction_id)
    saida = one(call.session, tx, call.identity.user_id)
    return ToolOutput(
        structured=TransactionResult(transaction=saida),
        summary=f"{saida.title}: {fmt_brl(saida.amount, saida.currency)} em {saida.date.isoformat()} ({saida.space.name}).",
        entity_type="transaction",
        entity_ids=[tx.id],
        space_id=tx.workspace_id,
        widget={"view": "transaction", "app_url": saida.app_url},
    )
