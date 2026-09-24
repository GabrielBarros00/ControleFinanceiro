"""`statements_get` e `statements_show`: a fatura de um cartão, com as compras e o
resumo por categoria. A primeira só devolve dados; a segunda faz a mesma consulta e
desenha o componente (ADR 0035, seção 8).

Somente leitura de verdade: se a fatura do ciclo ainda não existe (mês sem
compras), a resposta diz `exists: false` com as datas previstas — não cria a
fatura como a tela de cartões faz para se exibir.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field
from sqlmodel import select

from app.domain.dates import today_local
from app.mcp import resolve
from app.mcp.dates import MonthKey
from app.mcp.errors import ErrorCode, McpToolError
from app.mcp.money import MoneyOut, fmt_brl
from app.mcp.ui import WIDGET_URI
from app.mcp.registry import ToolCall, ToolInput, ToolOutput, tool
from app.mcp.schemas import Ref, TransactionBrief
from app.mcp.serializers import app_url, civil, load_bundle, to_brief
from app.models.credit_card import CardStatement, CreditCard
from app.models.transaction import Transaction
from app.services import transaction_query
from app.services.credit_card_service import CreditCardService
from app.services.oauth import scopes as escopos

WIDGET = WIDGET_URI


def card_or_only(call: ToolCall, card_id: Optional[int], card: Optional[str]) -> CreditCard:
    """O cartão pedido; sem nome, o único cartão da pessoa (senão AMBIGUOUS)."""
    cartao = resolve.resolve_card(call.session, call.identity.user_id, card_id=card_id, card=card)
    if cartao is not None:
        return cartao
    cartoes = resolve.user_cards(call.session, call.identity.user_id)
    if len(cartoes) == 1:
        return cartoes[0]
    if not cartoes:
        raise McpToolError(ErrorCode.NOT_FOUND, "Você não tem cartão de crédito cadastrado.")
    raise McpToolError(
        ErrorCode.AMBIGUOUS,
        "Você tem mais de um cartão. Pergunte ao usuário qual e informe `card_id`.",
        candidates=[{"id": c.id, "name": c.name} for c in cartoes],
        details={"kind": "cartão", "id_param": "card_id"},
    )


class StatementIn(ToolInput):
    card: Optional[str] = Field(None, max_length=120, description="Nome do cartão. Omitido: seu único cartão.")
    card_id: Optional[int] = None
    month: Optional[MonthKey] = Field(None, description="Mês da fatura (YYYY-MM). Omitido: a fatura do ciclo atual.")
    limit: int = Field(20, ge=1, le=100, description="Compras por página (o total e as categorias já cobrem a fatura inteira).")
    cursor: Optional[str] = Field(None, max_length=512)


class StatementPurchase(TransactionBrief):
    statement_amount: MoneyOut = Field(description="Valor desta compra na fatura (moeda do cartão).")


class CategoryShare(BaseModel):
    category: str
    amount: MoneyOut
    count: int


class StatementOut(BaseModel):
    card: Ref
    currency: str
    month: str
    exists: bool = Field(description="False = ainda não há compras nesta fatura.")
    status: str = Field(description="open | closed | paid | overdue (ou 'not_created').")
    closing_date: date
    due_date: date
    total: MoneyOut
    paid: MoneyOut
    balance: MoneyOut = Field(description="O que falta pagar desta fatura.")
    overdue: bool
    purchases_count: int
    purchases: List[StatementPurchase]
    next_cursor: Optional[str] = None
    by_category: List[CategoryShare]
    available_months: List[str] = Field(description="Faturas existentes deste cartão (mais recentes primeiro).")
    app_url: str


def _fatura(call: ToolCall, a: StatementIn) -> ToolOutput:
    """A consulta da fatura, compartilhada por `statements_get` (dados) e `statements_show` (tela)."""
    cartao = card_or_only(call, a.card_id, a.card)
    hoje = today_local()
    alvo = CreditCardService.preview_statement_target(call.session, cartao, hoje)
    mes = a.month or alvo["month"]
    fatura = call.session.exec(
        select(CardStatement).where(CardStatement.card_id == cartao.id, CardStatement.month == mes)
    ).first()
    meses = list(call.session.exec(
        select(CardStatement.month).where(CardStatement.card_id == cartao.id).order_by(CardStatement.month.desc()).limit(24)
    ).all())

    compras: list[Transaction] = []
    if fatura is not None:
        compras = list(call.session.exec(
            select(Transaction)
            .where(*CreditCardService.statement_population(fatura.id, cartao))
            .order_by(Transaction.transaction_date.desc(), Transaction.id.desc())
        ).all())

    impressao = f"stmt:{cartao.id}:{mes}"
    try:
        inicio = transaction_query.decode_cursor(a.cursor, impressao) if a.cursor else 0
    except transaction_query.InvalidCursor as exc:
        raise McpToolError(ErrorCode.VALIDATION_ERROR, str(exc))
    pagina = compras[inicio:inicio + a.limit]
    proximo = transaction_query.encode_cursor(inicio + a.limit, impressao) if inicio + a.limit < len(compras) else None

    pacote = load_bundle(call.session, compras)
    por_categoria: dict[str, list] = defaultdict(lambda: [Decimal("0"), 0])
    for tx in compras:
        valor = Decimal(tx.statement_amount if tx.statement_amount is not None else tx.total_amount)
        itens = [i for i in pacote.items.get(tx.id, []) if i.category_id]
        base = sum((Decimal(i.amount) for i in itens), Decimal("0"))
        if not itens or base <= 0:
            por_categoria["Sem categoria"][0] += valor
            por_categoria["Sem categoria"][1] += 1
            continue
        for item in itens:
            nome = pacote.categories.get(item.category_id, "?")
            por_categoria[nome][0] += (valor * Decimal(item.amount) / base).quantize(Decimal("0.01"))
        for nome in {pacote.categories.get(i.category_id, "?") for i in itens}:
            por_categoria[nome][1] += 1

    if fatura is not None:
        total = CreditCardService.effective_total(call.session, fatura)
        pago = CreditCardService.paid_amount(call.session, fatura)
        saldo = CreditCardService.statement_balance(call.session, fatura)
        situacao = getattr(fatura.status, "value", fatura.status)
        vencida = CreditCardService.is_overdue(fatura, hoje)
        fechamento, vencimento = civil(fatura.closing_date), civil(fatura.due_date)
    else:
        total = pago = saldo = Decimal("0")
        situacao, vencida = "not_created", False
        fechamento, vencimento = civil(alvo["closing_date"]), civil(alvo["due_date"])
        if a.month and a.month != alvo["month"]:
            from app.services.credit_card_service import _statement_dates

            ano, m = (int(p) for p in a.month.split("-"))
            f_dt, v_dt = _statement_dates(cartao, ano, m)
            fechamento, vencimento = civil(f_dt), civil(v_dt)

    saida = StatementOut(
        card=Ref(id=cartao.id, name=cartao.name),
        currency=cartao.currency,
        month=mes,
        exists=fatura is not None,
        status=situacao,
        closing_date=fechamento,
        due_date=vencimento,
        total=total,
        paid=pago,
        balance=saldo,
        overdue=vencida,
        purchases_count=len(compras),
        purchases=[
            StatementPurchase(
                **to_brief(tx, pacote, call.identity.user_id).model_dump(),
                statement_amount=tx.statement_amount if tx.statement_amount is not None else tx.total_amount,
            )
            for tx in pagina
        ],
        next_cursor=proximo,
        by_category=sorted(
            [CategoryShare(category=k, amount=v[0], count=v[1]) for k, v in por_categoria.items()],
            key=lambda c: c.amount, reverse=True,
        ),
        available_months=meses,
        app_url=app_url("/me/cards"),
    )
    resumo = (
        f"Fatura {mes} do {cartao.name}: {fmt_brl(total, cartao.currency)}, "
        f"vence em {vencimento.isoformat()}, saldo a pagar {fmt_brl(saldo, cartao.currency)}"
        f" ({len(compras)} compra(s))."
    )
    return ToolOutput(
        structured=saida,
        summary=resumo,
        entity_type="statement",
        entity_ids=[fatura.id] if fatura else [],
        widget={"view": "statement", "app_url": saida.app_url},
    )


@tool(
    name="statements_get",
    title="Ver fatura do cartão",
    description=(
        "Devolve a fatura de um cartão de crédito: total, quanto já foi pago, saldo, vencimento, as "
        "compras (paginadas) e o total por categoria. Só dados; para DESENHAR a fatura na conversa, "
        "use statements_show.\n"
        "Use quando: precisar dos números para responder ou analisar ('quanto vem na fatura', 'o que "
        "tem na fatura de outubro', comparar faturas).\n"
        "Não use quando: o usuário pedir para ver/mostrar a fatura (statements_show); quiser só o "
        "limite disponível (cards_list); ou for pagar a fatura (statements_pay)."
    ),
    input_model=StatementIn,
    output_model=StatementOut,
    scope=escopos.FINANCE_READ,
    kind="read",
    read_only=True,
    destructive=False,
    idempotent=True,
    cost=2,
    invoking="Lendo a fatura…",
    invoked="Fatura lida",
)
def statements_get(call: ToolCall) -> ToolOutput:
    return _fatura(call, call.args)


class StatementShowIn(ToolInput):
    card: Optional[str] = Field(None, max_length=120, description="Nome do cartão. Omitido: seu único cartão.")
    card_id: Optional[int] = None
    month: Optional[MonthKey] = Field(None, description="Mês da fatura (YYYY-MM). Omitido: a fatura do ciclo atual.")


#: O componente mostra as compras mais recentes; o resto fica no app ("Abrir no Controle Financeiro").
COMPRAS_NA_TELA = 6


@tool(
    name="statements_show",
    title="Mostrar fatura na conversa",
    description=(
        "Desenha a fatura de um cartão como componente visual na conversa (total, saldo, vencimento, "
        "as maiores categorias e as compras mais recentes) e devolve os mesmos dados de "
        "statements_get, só com a primeira página de compras.\n"
        "Use quando: o usuário pedir para ver ou mostrar a fatura ('mostre minha fatura do Nubank'). "
        "Chame uma vez, com a fatura final.\n"
        "Não use quando: precisar dos números para analisar, somar ou comparar (statements_get): "
        "cada chamada desenha um componente novo na conversa."
    ),
    input_model=StatementShowIn,
    output_model=StatementOut,
    scope=escopos.FINANCE_READ,
    kind="read",
    read_only=True,
    destructive=False,
    idempotent=True,
    cost=2,
    ui=WIDGET,
    invoking="Abrindo a fatura…",
    invoked="Fatura aberta",
    meta={"openai/widgetDescription": (
        "O componente já mostra a fatura: total, saldo, vencimento, categorias e as compras mais "
        "recentes. Não liste as compras de novo; responda em uma ou duas frases."
    )},
)
def statements_show(call: ToolCall) -> ToolOutput:
    a: StatementShowIn = call.args
    return _fatura(call, StatementIn(card=a.card, card_id=a.card_id, month=a.month, limit=COMPRAS_NA_TELA))
