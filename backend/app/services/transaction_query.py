"""Busca de lançamentos com filtros de domínio, atravessando os espaços da pessoa.

A listagem REST (`GET /{ws}/transactions`) serve a TELA: um espaço, um mês,
paginação por número de página. Um agente pergunta outra coisa — "a compra do
McDonald's de ontem", "tudo que foi no Nubank este mês", "o que eu dividi com a
Ana" —, e por isso esta consulta aceita período por DIA, texto, cartão, conta,
pessoa e faixa de valor, em todos os espaços de uma vez.

**A visibilidade é a MESMA da listagem** (ADR 0018): cada espaço entra com o
`transaction_scope` do membership da pessoa NAQUELE espaço, num `OR` de
`(workspace = X AND escopo de X)`. Quem só vê "o que o envolve" numa casa continua
vendo só isso — aqui também. Filtro nenhum amplia o que o escopo corta.

**Totais sobre o filtro inteiro, não sobre a página**, com a mesma política das
agregações (ADR 0003/0006): só status realizados, somados por moeda — moedas
diferentes nunca viram um número só.

Somente leitura: nada aqui materializa recorrência nem cria fatura.
"""
from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Iterable, List, Optional, Sequence

from sqlalchemy import and_, exists, false, func, or_
from sqlmodel import Session, select

from app.domain.access_policy import involvement_filter, transaction_scope
from app.domain.dates import app_tz
from app.domain.query_policy import REALIZED_STATUSES
from app.models.tag import TransactionTagLink
from app.models.transaction import (
    PaymentMethod,
    Transaction,
    TransactionItem,
    TransactionPayer,
    TransactionSplit,
    TransactionStatus,
)
from app.models.workspace import WorkspaceMembership

MAX_LIMIT = 50
SORTS = ("date_desc", "date_asc", "amount_desc", "amount_asc")


class InvalidCursor(ValueError):
    pass


@dataclass
class TxFilters:
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    month: Optional[str] = None
    text: Optional[str] = None
    card_id: Optional[int] = None
    account_id: Optional[int] = None
    #: Mais de um id quando o MESMO nome de categoria/tag existe em espaços
    #: diferentes (cada espaço tem o seu "Alimentação").
    category_ids: Optional[Sequence[int]] = None
    tag_ids: Optional[Sequence[int]] = None
    person_id: Optional[int] = None
    payment_method: Optional[str] = None
    statuses: Sequence[str] = field(default_factory=tuple)
    settled: Optional[bool] = None
    min_amount: Optional[Decimal] = None
    max_amount: Optional[Decimal] = None
    installment_group_id: Optional[str] = None
    uncategorized: bool = False
    ids: Optional[Sequence[int]] = None

    def fingerprint(self, space_ids: Iterable[int], sort: str) -> str:
        dados = {k: (str(v) if v is not None else None) for k, v in self.__dict__.items()}
        dados["spaces"] = sorted(space_ids)
        dados["sort"] = sort
        return hashlib.sha256(json.dumps(dados, sort_keys=True).encode()).hexdigest()[:16]


@dataclass
class TxPage:
    items: List[Transaction]
    total_count: int
    totals: List[dict]
    my_share_totals: List[dict]
    next_cursor: Optional[str]


def _instante_utc(dia: date) -> datetime:
    """Meia-noite LOCAL do dia, como instante UTC ingênuo (como as colunas guardam)."""
    return datetime.combine(dia, time(0), tzinfo=app_tz()).astimezone(UTC).replace(tzinfo=None)


def encode_cursor(offset: int, fingerprint: str) -> str:
    return base64.urlsafe_b64encode(json.dumps({"o": offset, "f": fingerprint}).encode()).decode().rstrip("=")


def decode_cursor(cursor: str, fingerprint: str) -> int:
    try:
        preenchido = cursor + "=" * (-len(cursor) % 4)
        dados = json.loads(base64.urlsafe_b64decode(preenchido.encode()).decode())
        offset = int(dados["o"])
    except Exception:
        raise InvalidCursor("cursor inválido")
    if dados.get("f") != fingerprint or offset < 0:
        raise InvalidCursor("o cursor pertence a outra busca — refaça a busca sem cursor")
    return offset


def _base(memberships: Sequence[WorkspaceMembership]):
    if not memberships:
        return select(Transaction).where(false())
    escopos = [
        and_(Transaction.workspace_id == m.workspace_id, transaction_scope(m)) for m in memberships
    ]
    return select(Transaction).where(Transaction.deleted_at.is_(None), or_(*escopos))


def build_statement(memberships: Sequence[WorkspaceMembership], f: TxFilters):
    consulta = _base(memberships)
    if f.ids is not None:
        consulta = consulta.where(Transaction.id.in_(list(f.ids) or [-1]))
    if f.month:
        consulta = consulta.where(Transaction.billing_month == f.month)
    if f.date_from:
        consulta = consulta.where(Transaction.transaction_date >= _instante_utc(f.date_from))
    if f.date_to:
        consulta = consulta.where(Transaction.transaction_date < _instante_utc(f.date_to + timedelta(days=1)))
    if f.text:
        termo = f.text.lower()
        consulta = consulta.where(or_(
            func.lower(Transaction.title).contains(termo, autoescape=True),
            func.lower(func.coalesce(Transaction.description, "")).contains(termo, autoescape=True),
        ))
    if f.card_id is not None:
        consulta = consulta.where(Transaction.credit_card_id == f.card_id)
    if f.account_id is not None:
        consulta = consulta.where(Transaction.id.in_(
            select(TransactionPayer.transaction_id).where(TransactionPayer.account_id == f.account_id)
        ))
    if f.category_ids is not None:
        consulta = consulta.where(exists(
            select(TransactionItem.id).where(
                TransactionItem.transaction_id == Transaction.id,
                TransactionItem.category_id.in_(list(f.category_ids) or [-1]),
            )
        ))
    if f.uncategorized:
        consulta = consulta.where(~exists(
            select(TransactionItem.id).where(
                TransactionItem.transaction_id == Transaction.id,
                TransactionItem.category_id.is_not(None),
            )
        ))
    if f.tag_ids is not None:
        consulta = consulta.where(exists(
            select(TransactionTagLink.tag_id).where(
                TransactionTagLink.transaction_id == Transaction.id,
                TransactionTagLink.tag_id.in_(list(f.tag_ids) or [-1]),
            )
        ))
    if f.person_id is not None:
        consulta = consulta.where(involvement_filter(f.person_id))
    if f.payment_method:
        consulta = consulta.where(Transaction.payment_method == PaymentMethod(f.payment_method))
    if f.statuses:
        consulta = consulta.where(Transaction.status.in_([TransactionStatus(s) for s in f.statuses]))
    if f.settled is not None:
        consulta = consulta.where(
            Transaction.settled_at.is_not(None)
            if f.settled
            else and_(Transaction.settled_at.is_(None), Transaction.credit_card_id.is_(None))
        )
    if f.min_amount is not None:
        consulta = consulta.where(Transaction.total_amount >= f.min_amount)
    if f.max_amount is not None:
        consulta = consulta.where(Transaction.total_amount <= f.max_amount)
    if f.installment_group_id:
        consulta = consulta.where(Transaction.installment_group_id == f.installment_group_id)
    return consulta


def _ordena(consulta, sort: str):
    if sort == "date_asc":
        return consulta.order_by(Transaction.transaction_date.asc(), Transaction.id.asc())
    if sort == "amount_desc":
        return consulta.order_by(Transaction.total_amount.desc(), Transaction.id.desc())
    if sort == "amount_asc":
        return consulta.order_by(Transaction.total_amount.asc(), Transaction.id.asc())
    return consulta.order_by(Transaction.transaction_date.desc(), Transaction.id.desc())


def search(
    session: Session,
    memberships: Sequence[WorkspaceMembership],
    filtros: TxFilters,
    *,
    me_id: int,
    limit: int = 20,
    cursor: Optional[str] = None,
    sort: str = "date_desc",
) -> TxPage:
    limit = max(1, min(limit, MAX_LIMIT))
    impressao = filtros.fingerprint([m.workspace_id for m in memberships], sort)
    offset = decode_cursor(cursor, impressao) if cursor else 0

    consulta = build_statement(memberships, filtros)
    sub = consulta.subquery()
    total = session.exec(select(func.count()).select_from(sub)).one()

    totais = session.exec(
        select(sub.c.currency, func.coalesce(func.sum(sub.c.total_amount), 0), func.count())
        .where(sub.c.status.in_(REALIZED_STATUSES))
        .group_by(sub.c.currency)
    ).all()
    minha_parte = session.exec(
        select(sub.c.currency, func.coalesce(func.sum(TransactionSplit.computed_amount), 0), func.count())
        .join(TransactionSplit, TransactionSplit.transaction_id == sub.c.id)
        .where(sub.c.status.in_(REALIZED_STATUSES), TransactionSplit.user_id == me_id)
        .group_by(sub.c.currency)
    ).all()

    linhas = list(session.exec(_ordena(consulta, sort).offset(offset).limit(limit)).all())
    proximo = encode_cursor(offset + limit, impressao) if offset + limit < total else None
    return TxPage(
        items=linhas,
        total_count=int(total),
        totals=[{"currency": c, "amount": Decimal(a), "count": int(n)} for c, a, n in totais],
        my_share_totals=[{"currency": c, "amount": Decimal(a), "count": int(n)} for c, a, n in minha_parte],
        next_cursor=proximo,
    )
