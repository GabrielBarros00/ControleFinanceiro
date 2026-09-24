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
from app.mcp import versioning
from app.mcp.schemas import (
    AdjustmentOut,
    AttachmentOut,
    ForeignInfo,
    InstallmentInfo,
    ItemOut,
    PersonAmount,
    PurchaseOut,
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
    SplitMode,
    Transaction,
    TransactionAdjustment,
    TransactionItem,
    TransactionItemShare,
    TransactionPayer,
    TransactionSplit,
    TransactionStatus,
)
from app.models.user import User
from app.models.workspace import Workspace
from app.services.commands.transactions import _strip_installment_suffix


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
    shares: dict[int, list[TransactionItemShare]] = field(default_factory=lambda: defaultdict(list))
    adjustments: dict[int, list[TransactionAdjustment]] = field(default_factory=lambda: defaultdict(list))
    files: dict[int, list] = field(default_factory=lambda: defaultdict(list))


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

    item_ids = [i.id for its in pacote.items.values() for i in its]
    if item_ids:
        for sh in session.exec(
            select(TransactionItemShare).where(TransactionItemShare.item_id.in_(item_ids))
        ).all():
            pacote.shares[sh.item_id].append(sh)
    for aj in session.exec(
        select(TransactionAdjustment).where(TransactionAdjustment.transaction_id.in_(ids))
        .order_by(TransactionAdjustment.id)
    ).all():
        pacote.adjustments[aj.transaction_id].append(aj)
    # Só os metadados: a coluna `data` (conteúdo legado) nunca é lida aqui.
    for linha in session.exec(
        select(
            Attachment.id, Attachment.transaction_id, Attachment.filename, Attachment.content_type,
            Attachment.size_bytes, Attachment.uploaded_by_user_id, Attachment.created_at,
        ).where(Attachment.transaction_id.in_(ids)).order_by(Attachment.created_at, Attachment.id)
    ).all():
        pacote.files[linha.transaction_id].append(linha)

    user_ids = {t.created_by_user_id for t in lista if t.created_by_user_id}
    user_ids |= {p.user_id for ps in pacote.payers.values() for p in ps}
    user_ids |= {s.user_id for ss in pacote.splits.values() for s in ss}
    user_ids |= {sh.user_id for shs in pacote.shares.values() for sh in shs}
    user_ids |= {f.uploaded_by_user_id for fs in pacote.files.values() for f in fs if f.uploaded_by_user_id}
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


def _quantidade(q) -> str:
    texto = format(Decimal(q).normalize(), "f")
    return texto if "." not in texto else texto.rstrip("0").rstrip(".")


def _itens(pacote: TxBundle, tx: Transaction, me_id: int) -> list[ItemOut]:
    """Os itens da nota — vazio quando o lançamento não foi detalhado.

    Todo lançamento com categoria tem UM item-sombra (título e valor do próprio
    lançamento), que o app usa para guardar a categoria. Mostrá-lo como "item"
    só repetiria o lançamento: ele aparece quando há mais de um item, divisão por
    item, ajustes, ou quando a única linha diz algo a mais (quantidade, unitário).
    """
    itens = pacote.items.get(tx.id, [])
    por_item = _valor(tx.split_mode) == SplitMode.item.value
    detalhado = (
        len(itens) > 1 or por_item or bool(pacote.adjustments.get(tx.id))
        or any(Decimal(i.quantity) != 1 or i.unit_amount is not None or i.description for i in itens)
    )
    if not detalhado:
        return []
    saida = []
    for i in itens:
        partes = pacote.shares.get(i.id, []) if por_item else []
        saida.append(ItemOut(
            title=i.title,
            description=i.description,
            quantity=_quantidade(i.quantity),
            unit_amount=i.unit_amount,
            amount=i.amount,
            category=Ref(id=i.category_id, name=pacote.categories.get(i.category_id, "?")) if i.category_id else None,
            shares=_pessoas(pacote, partes, me_id, "computed_amount"),
            my_share=sum((Decimal(s.computed_amount) for s in partes if s.user_id == me_id), Decimal("0.00")) if por_item else None,
        ))
    return saida


def _arquivos(pacote: TxBundle, tx: Transaction) -> list[AttachmentOut]:
    return [
        AttachmentOut(
            id=f.id,
            filename=f.filename,
            content_type=f.content_type,
            size_bytes=f.size_bytes,
            uploaded_by=Ref(id=f.uploaded_by_user_id, name=pacote.users.get(f.uploaded_by_user_id, "?"))
            if f.uploaded_by_user_id else None,
            uploaded_on=local_day(f.created_at) if f.created_at else None,
        )
        for f in pacote.files.get(tx.id, [])
    ]


def to_out(tx: Transaction, pacote: TxBundle, me_id: int, purchase: Optional[PurchaseOut] = None) -> TransactionOut:
    categorias = _categorias(pacote, tx)
    estrangeiro = None
    if tx.original_amount is not None and tx.original_currency:
        estrangeiro = ForeignInfo(
            original_amount=tx.original_amount,
            original_currency=tx.original_currency,
            exchange_rate=str(tx.exchange_rate) if tx.exchange_rate is not None else None,
            iof_rate=str(tx.iof_rate) if tx.iof_rate is not None else None,
        )
    saida = TransactionOut(
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
        split_mode=_valor(tx.split_mode) or SplitMode.transaction.value,
        payers=_pessoas(pacote, pacote.payers.get(tx.id, []), me_id, "amount"),
        split=_pessoas(pacote, pacote.splits.get(tx.id, []), me_id, "computed_amount"),
        my_share=my_share(pacote, tx, me_id),
        items=_itens(pacote, tx, me_id),
        adjustments=[
            AdjustmentOut(type=_valor(a.type), amount=a.amount, description=a.description)
            for a in pacote.adjustments.get(tx.id, [])
        ],
        purchase=purchase,
        created_by=Ref(id=tx.created_by_user_id, name=pacote.users.get(tx.created_by_user_id, "?")) if tx.created_by_user_id else None,
        foreign=estrangeiro,
        attachments=int(pacote.attachments.get(tx.id, 0)),
        files=_arquivos(pacote, tx),
        app_url=transaction_url(tx),
    )
    saida.version = versioning.version_of(saida)
    return saida


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


def siblings(session: Session, tx: Transaction) -> list[Transaction]:
    """As parcelas vivas da mesma compra, em ordem."""
    if not tx.installment_group_id:
        return [tx]
    return list(session.exec(
        select(Transaction)
        .where(
            Transaction.workspace_id == tx.workspace_id,
            Transaction.installment_group_id == tx.installment_group_id,
            Transaction.deleted_at.is_(None),
        )
        .order_by(Transaction.installment_no, Transaction.id)
    ).all())


def purchase_of(session: Session, tx: Transaction, me_id: int) -> Optional[PurchaseOut]:
    """A compra inteira de um parcelado: somas por pessoa e por item, das parcelas vivas.

    Os itens de uma compra parcelada estão FATIADOS nas parcelas (cada uma leva a
    sua fração de cada item, `_plan_installment_items`). Aqui eles são remontados
    pela posição, para o modelo e a tela verem "arroz R$ 30", não "arroz R$ 15"
    duas vezes. Só leitura: a regra de fatiar continua no comando do app.
    """
    if not tx.installment_group_id:
        return None
    irmas = siblings(session, tx)
    pacote = load_bundle(session, irmas)
    total = sum((Decimal(t.total_amount) for t in irmas), Decimal("0.00"))
    por_pessoa: dict[int, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for t in irmas:
        for s in pacote.splits.get(t.id, []):
            por_pessoa[s.user_id] += Decimal(s.computed_amount)
    linhas: dict[int, dict] = {}
    for t in irmas:
        for i in pacote.items.get(t.id, []):
            agg = linhas.setdefault(i.position, {"item": i, "amount": Decimal("0.00"), "shares": defaultdict(lambda: Decimal("0.00"))})
            agg["amount"] += Decimal(i.amount)
            for sh in pacote.shares.get(i.id, []):
                agg["shares"][sh.user_id] += Decimal(sh.computed_amount)
    por_item = _valor(tx.split_mode) == SplitMode.item.value
    itens = []
    if por_item or len(linhas) > 1:
        for pos in sorted(linhas):
            agg = linhas[pos]
            i = agg["item"]
            partes = [
                PersonAmount(person=Ref(id=uid, name=pacote.users.get(uid, f"Pessoa {uid}")), amount=v, is_me=uid == me_id)
                for uid, v in agg["shares"].items()
            ]
            itens.append(ItemOut(
                title=i.title,
                description=i.description,
                quantity="1",
                amount=agg["amount"],
                category=Ref(id=i.category_id, name=pacote.categories.get(i.category_id, "?")) if i.category_id else None,
                shares=partes if por_item else [],
                my_share=agg["shares"].get(me_id, Decimal("0.00")) if por_item else None,
            ))
    return PurchaseOut(
        group_id=tx.installment_group_id,
        title=_strip_installment_suffix(tx.title),
        amount=total,
        currency=tx.currency,
        installments=tx.installments_of or len(irmas),
        paid_installments=sum(1 for t in irmas if t.status == TransactionStatus.paid or t.settled_at is not None),
        split=[
            PersonAmount(person=Ref(id=uid, name=pacote.users.get(uid, f"Pessoa {uid}")), amount=v, is_me=uid == me_id)
            for uid, v in por_pessoa.items()
        ],
        my_share=por_pessoa.get(me_id, Decimal("0.00")),
        items=itens,
    )


def one(session: Session, tx: Transaction, me_id: int) -> TransactionOut:
    pacote = load_bundle(session, [tx])
    return to_out(tx, pacote, me_id, purchase=purchase_of(session, tx, me_id))


def civil(value) -> Optional[object]:
    """Dia civil de uma coluna que guarda DIA (fatura: fechamento/vencimento)."""
    return civil_day(value) if value is not None else None
