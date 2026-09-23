"""Lançamento (ORM) → saída do MCP, com carga em LOTE.

Uma listagem de 50 lançamentos não pode virar 50 × (pagadores + divisão + itens
+ tags + nomes) consultas. `load_bundle` busca tudo que a serialização precisa
em um punhado de SELECTs com `IN (...)`, e `to_out`/`to_brief` só leem do
pacote.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable, Optional
from urllib.parse import urlencode

from sqlmodel import Session, func, select

from app.core.config import settings
from app.domain.dates import civil_day, local_day
from app.mcp.schemas import (
    ForeignInfo,
    InstallmentInfo,
    PersonAmount,
    Ref,
    StatementRef,
    TransactionBrief,
    TransactionOut,
)
from app.models.attachment import Attachment
from app.models.category import Category
from app.models.credit_card import CardStatement, CreditCard
from app.models.tag import Tag, TransactionTagLink
from app.models.transaction import (
    Transaction,
    TransactionItem,
    TransactionPayer,
    TransactionSplit,
)
from app.models.user import User
from app.models.workspace import Workspace


def app_url(path: str, **query: str) -> str:
    sufixo = f"?{urlencode({k: v for k, v in query.items() if v})}" if query else ""
    return f"{settings.oauth_issuer}{path}{sufixo}"


def transaction_url(tx: Transaction) -> str:
    return app_url(f"/w/{tx.workspace_id}/transactions", month=tx.billing_month or "", q=tx.title[:60])


def _valor(v) -> str:
    return getattr(v, "value", v)


@dataclass
class TxBundle:
    payers: dict[int, list[TransactionPayer]] = field(default_factory=lambda: defaultdict(list))
    splits: dict[int, list[TransactionSplit]] = field(default_factory=lambda: defaultdict(list))
    items: dict[int, list[TransactionItem]] = field(default_factory=lambda: defaultdict(list))
    tags: dict[int, list[str]] = field(default_factory=lambda: defaultdict(list))
    users: dict[int, str] = field(default_factory=dict)
    categories: dict[int, str] = field(default_factory=dict)
    cards: dict[int, str] = field(default_factory=dict)
    statements: dict[int, str] = field(default_factory=dict)
    spaces: dict[int, str] = field(default_factory=dict)
    attachments: dict[int, int] = field(default_factory=dict)


def load_bundle(session: Session, txs: Iterable[Transaction]) -> TxBundle:
    lista = list(txs)
    pacote = TxBundle()
    if not lista:
        return pacote
    ids = [t.id for t in lista]

    for p in session.exec(select(TransactionPayer).where(TransactionPayer.transaction_id.in_(ids))).all():
        pacote.payers[p.transaction_id].append(p)
    for s in session.exec(select(TransactionSplit).where(TransactionSplit.transaction_id.in_(ids))).all():
        pacote.splits[s.transaction_id].append(s)
    for i in session.exec(
        select(TransactionItem).where(TransactionItem.transaction_id.in_(ids)).order_by(TransactionItem.position)
    ).all():
        pacote.items[i.transaction_id].append(i)
    for tx_id, nome in session.exec(
        select(TransactionTagLink.transaction_id, Tag.name)
        .join(Tag, Tag.id == TransactionTagLink.tag_id)
        .where(TransactionTagLink.transaction_id.in_(ids))
    ).all():
        pacote.tags[tx_id].append(nome)

    user_ids = {t.created_by_user_id for t in lista if t.created_by_user_id}
    user_ids |= {p.user_id for ps in pacote.payers.values() for p in ps}
    user_ids |= {s.user_id for ss in pacote.splits.values() for s in ss}
    if user_ids:
        pacote.users = dict(session.exec(select(User.id, User.name).where(User.id.in_(user_ids))).all())

    cat_ids = {i.category_id for its in pacote.items.values() for i in its if i.category_id}
    if cat_ids:
        pacote.categories = dict(session.exec(select(Category.id, Category.name).where(Category.id.in_(cat_ids))).all())
    card_ids = {t.credit_card_id for t in lista if t.credit_card_id}
    if card_ids:
        pacote.cards = dict(session.exec(select(CreditCard.id, CreditCard.name).where(CreditCard.id.in_(card_ids))).all())
    stmt_ids = {t.statement_id for t in lista if t.statement_id}
    if stmt_ids:
        pacote.statements = dict(session.exec(
            select(CardStatement.id, CardStatement.month).where(CardStatement.id.in_(stmt_ids))
        ).all())
    ws_ids = {t.workspace_id for t in lista}
    pacote.spaces = dict(session.exec(select(Workspace.id, Workspace.name).where(Workspace.id.in_(ws_ids))).all())
    pacote.attachments = dict(session.exec(
        select(Attachment.transaction_id, func.count())
        .where(Attachment.transaction_id.in_(ids))
        .group_by(Attachment.transaction_id)
    ).all())
    return pacote


def my_share(pacote: TxBundle, tx: Transaction, me_id: int) -> Decimal:
    return sum(
        (Decimal(s.computed_amount) for s in pacote.splits.get(tx.id, []) if s.user_id == me_id),
        Decimal("0.00"),
    )


def _pessoas(pacote: TxBundle, linhas, me_id: int, campo: str) -> list[PersonAmount]:
    return [
        PersonAmount(
            person=Ref(id=x.user_id, name=pacote.users.get(x.user_id, f"Pessoa {x.user_id}")),
            amount=getattr(x, campo),
            is_me=x.user_id == me_id,
        )
        for x in linhas
    ]


def _categorias(pacote: TxBundle, tx: Transaction) -> list[Ref]:
    vistos: dict[int, Ref] = {}
    for item in pacote.items.get(tx.id, []):
        if item.category_id and item.category_id not in vistos:
            vistos[item.category_id] = Ref(id=item.category_id, name=pacote.categories.get(item.category_id, "?"))
    return list(vistos.values())


def to_out(tx: Transaction, pacote: TxBundle, me_id: int) -> TransactionOut:
    categorias = _categorias(pacote, tx)
    estrangeiro = None
    if tx.original_amount is not None and tx.original_currency:
        estrangeiro = ForeignInfo(
            original_amount=tx.original_amount,
            original_currency=tx.original_currency,
            exchange_rate=str(tx.exchange_rate) if tx.exchange_rate is not None else None,
            iof_rate=str(tx.iof_rate) if tx.iof_rate is not None else None,
        )
    return TransactionOut(
        id=tx.id,
        space=Ref(id=tx.workspace_id, name=pacote.spaces.get(tx.workspace_id, "?")),
        title=tx.title,
        description=tx.description,
        date=local_day(tx.transaction_date),
        billing_month=tx.billing_month,
        amount=tx.total_amount,
        currency=tx.currency,
        status=_valor(tx.status),
        settled=tx.settled_at is not None,
        settled_on=local_day(tx.settled_at) if tx.settled_at else None,
        payment_method=_valor(tx.payment_method) if tx.payment_method else None,
        card=Ref(id=tx.credit_card_id, name=pacote.cards.get(tx.credit_card_id, "?")) if tx.credit_card_id else None,
        statement=StatementRef(id=tx.statement_id, month=pacote.statements.get(tx.statement_id, "")) if tx.statement_id else None,
        category=categorias[0] if len(categorias) == 1 else None,
        categories=categorias if len(categorias) > 1 else [],
        tags=sorted(pacote.tags.get(tx.id, [])),
        installment=InstallmentInfo(
            number=tx.installment_no, of=tx.installments_of, group_id=tx.installment_group_id
        ) if tx.installment_no and tx.installments_of else None,
        payers=_pessoas(pacote, pacote.payers.get(tx.id, []), me_id, "amount"),
        split=_pessoas(pacote, pacote.splits.get(tx.id, []), me_id, "computed_amount"),
        my_share=my_share(pacote, tx, me_id),
        created_by=Ref(id=tx.created_by_user_id, name=pacote.users.get(tx.created_by_user_id, "?")) if tx.created_by_user_id else None,
        foreign=estrangeiro,
        attachments=int(pacote.attachments.get(tx.id, 0)),
        app_url=transaction_url(tx),
    )


def to_brief(tx: Transaction, pacote: TxBundle, me_id: int) -> TransactionBrief:
    categorias = _categorias(pacote, tx)
    return TransactionBrief(
        id=tx.id,
        space=Ref(id=tx.workspace_id, name=pacote.spaces.get(tx.workspace_id, "?")),
        date=local_day(tx.transaction_date),
        title=tx.title,
        amount=tx.total_amount,
        currency=tx.currency,
        my_share=my_share(pacote, tx, me_id),
        status=_valor(tx.status),
        settled=tx.settled_at is not None,
        payment_method=_valor(tx.payment_method) if tx.payment_method else None,
        card=pacote.cards.get(tx.credit_card_id) if tx.credit_card_id else None,
        category=categorias[0].name if len(categorias) == 1 else ("(várias)" if categorias else None),
        installment=f"{tx.installment_no}/{tx.installments_of}" if tx.installment_no and tx.installments_of else None,
        tags=sorted(pacote.tags.get(tx.id, [])),
    )


def one(session: Session, tx: Transaction, me_id: int) -> TransactionOut:
    return to_out(tx, load_bundle(session, [tx]), me_id)


def civil(value) -> Optional[object]:
    """Dia civil de uma coluna que guarda DIA (fatura: fechamento/vencimento)."""
    return civil_day(value) if value is not None else None
