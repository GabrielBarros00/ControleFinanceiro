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
from app.models.import_batch import ImportRow
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
    #: Os lançamentos criados por um lote de importação (desfazer importação).
    import_batch_id: Optional[int] = None

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
    if f.import_batch_id is not None:
        consulta = consulta.where(Transaction.id.in_(
            select(ImportRow.transaction_id).where(
                ImportRow.batch_id == f.import_batch_id, ImportRow.transaction_id.is_not(None),
            )
        ))
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


# --- Agrupamento (reports_breakdown) --------------------------------------------------

#: Teto de lançamentos que um agrupamento lê de uma vez. Acima disto o filtro é
#: largo demais para uma resposta de conversa: a tool pede um período menor.
BREAKDOWN_MAX_ROWS = 20_000
GROUP_KEYS = ("category", "tag", "person", "card", "account", "payment_method", "month", "space", "title")


class BreakdownTooLarge(ValueError):
    pass


@dataclass
class Group:
    key: str
    id: Optional[int]
    name: str
    currency: str
    amount: Decimal
    count: int


def _normaliza_titulo(titulo: str) -> str:
    """"Mercado Lela (2/3)" e "MERCADO LELA" viram o mesmo grupo."""
    import re
    import unicodedata

    t = re.sub(r"\s*\(\d+/\d+\)\s*$", "", titulo or "")
    t = "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))
    return " ".join(t.casefold().split())


def breakdown(
    session: Session,
    memberships: Sequence[WorkspaceMembership],
    filtros: TxFilters,
    *,
    me_id: int,
    group_by: str,
    basis: str = "my_share",
) -> List[Group]:
    """Soma o filtro por um eixo, com a MESMA regra da busca e dos relatórios.

    - Só status realizados (ADR 0003), por moeda (moedas nunca se somam).
    - `basis=my_share`: a SUA parte (ADR 0019). Na divisão por item, a share da
      pessoa no item; na divisão pela despesa, a parte dela rateada pelos itens em
      centavos exatos (`_allocate_proportional`) — o mesmo cálculo de
      `ReportService._my_categorized`.
    - `group_by=person` soma a parte de CADA pessoa (quem consumiu quanto), e
      `tag` conta o lançamento em cada tag que ele tem.
    """
    from app.models.category import Category
    from app.models.credit_card import CreditCard
    from app.models.payment_account import PaymentAccount
    from app.models.tag import Tag
    from app.models.transaction import SplitMode, TransactionItemShare
    from app.models.user import User
    from app.models.workspace import Workspace
    from app.services.transaction_service import _allocate_proportional, _cents

    sub = build_statement(memberships, filtros).where(Transaction.status.in_(REALIZED_STATUSES)).subquery()
    linhas = session.exec(
        select(
            sub.c.id, sub.c.currency, sub.c.total_amount, sub.c.split_mode, sub.c.credit_card_id,
            sub.c.payment_method, sub.c.billing_month, sub.c.workspace_id, sub.c.title,
        ).limit(BREAKDOWN_MAX_ROWS + 1)
    ).all()
    if len(linhas) > BREAKDOWN_MAX_ROWS:
        raise BreakdownTooLarge("filtro largo demais para agrupar: use um período menor")
    if not linhas:
        return []
    txs = {r.id: r for r in linhas}
    ids = list(txs)

    minha = dict(session.exec(
        select(TransactionSplit.transaction_id, TransactionSplit.computed_amount)
        .where(TransactionSplit.transaction_id.in_(ids), TransactionSplit.user_id == me_id)
    ).all())

    def valor(tx_id: int) -> Decimal:
        return Decimal(minha.get(tx_id, 0)) if basis == "my_share" else Decimal(txs[tx_id].total_amount)

    acumulado: dict[tuple, list] = {}

    def soma(chave_id, nome: str, moeda: str, quanto: Decimal, tx_id: int, contados: dict) -> None:
        if quanto == 0 and basis == "my_share":
            return
        k = (chave_id if chave_id is not None else f"~{nome}", moeda)
        linha = acumulado.setdefault(k, [chave_id, nome, moeda, Decimal("0.00"), 0])
        linha[3] += quanto
        if (k, tx_id) not in contados:
            contados[(k, tx_id)] = True
            linha[4] += 1

    contados: dict = {}
    if group_by == "category":
        nomes = dict(session.exec(select(Category.id, Category.name).where(Category.workspace_id.in_({r.workspace_id for r in linhas}))).all())
        itens: dict[int, list] = {}
        for item in session.exec(
            select(TransactionItem).where(TransactionItem.transaction_id.in_(ids))
            .order_by(TransactionItem.position, TransactionItem.id)
        ).all():
            itens.setdefault(item.transaction_id, []).append(item)
        shares: dict[int, Decimal] = {}
        if basis == "my_share":
            por_item = [i.id for its in itens.values() for i in its if txs[i.transaction_id].split_mode == SplitMode.item]
            if por_item:
                shares = dict(session.exec(
                    select(TransactionItemShare.item_id, TransactionItemShare.computed_amount)
                    .where(TransactionItemShare.item_id.in_(por_item), TransactionItemShare.user_id == me_id)
                ).all())
        for tx_id, r in txs.items():
            its = [i for i in itens.get(tx_id, []) if i.category_id]
            total_tx = valor(tx_id)
            if not its:
                soma(None, "Sem categoria", r.currency, total_tx, tx_id, contados)
                continue
            if basis == "my_share" and r.split_mode == SplitMode.item:
                alocado = {i.id: Decimal(shares.get(i.id, 0)) for i in its}
            else:
                todos = itens.get(tx_id, [])
                pesos = {k: _cents(i.amount) for k, i in enumerate(todos)}
                if sum(pesos.values()) <= 0:
                    pesos = {k: 1 for k in range(len(todos))}
                partes = _allocate_proportional(_cents(total_tx), pesos)
                alocado = {i.id: Decimal(partes[k]) / 100 for k, i in enumerate(todos)}
            sem = total_tx - sum((alocado.get(i.id, Decimal("0")) for i in its), Decimal("0"))
            for i in its:
                soma(i.category_id, nomes.get(i.category_id, "?"), r.currency, alocado.get(i.id, Decimal("0")), tx_id, contados)
            if sem > 0:
                soma(None, "Sem categoria", r.currency, sem, tx_id, contados)
    elif group_by == "tag":
        vinculos: dict[int, list] = {}
        for tx_id, tag_id, nome in session.exec(
            select(TransactionTagLink.transaction_id, Tag.id, Tag.name)
            .join(Tag, Tag.id == TransactionTagLink.tag_id)
            .where(TransactionTagLink.transaction_id.in_(ids))
        ).all():
            vinculos.setdefault(tx_id, []).append((tag_id, nome))
        for tx_id, r in txs.items():
            for tag_id, nome in vinculos.get(tx_id) or [(None, "Sem tag")]:
                soma(tag_id, nome, r.currency, valor(tx_id), tx_id, contados)
    elif group_by == "person":
        partes = session.exec(
            select(TransactionSplit.transaction_id, TransactionSplit.user_id, TransactionSplit.computed_amount)
            .where(TransactionSplit.transaction_id.in_(ids))
        ).all()
        nomes = dict(session.exec(select(User.id, User.name).where(User.id.in_({p.user_id for p in partes}))).all()) if partes else {}
        for tx_id, uid, quanto in partes:
            soma(uid, nomes.get(uid, f"Pessoa {uid}"), txs[tx_id].currency, Decimal(quanto), tx_id, contados)
    elif group_by == "card":
        nomes = dict(session.exec(select(CreditCard.id, CreditCard.name).where(CreditCard.owner_user_id == me_id)).all())
        for tx_id, r in txs.items():
            if r.credit_card_id and r.credit_card_id in nomes:
                soma(r.credit_card_id, nomes[r.credit_card_id], r.currency, valor(tx_id), tx_id, contados)
            else:
                soma(None, "Fora do cartão" if not r.credit_card_id else "Cartão de outra pessoa", r.currency, valor(tx_id), tx_id, contados)
    elif group_by == "account":
        nomes = dict(session.exec(select(PaymentAccount.id, PaymentAccount.name).where(PaymentAccount.owner_user_id == me_id)).all())
        contas = {}
        for tx_id, conta_id in session.exec(
            select(TransactionPayer.transaction_id, TransactionPayer.account_id).where(TransactionPayer.transaction_id.in_(ids))
        ).all():
            contas.setdefault(tx_id, conta_id)
        for tx_id, r in txs.items():
            c = contas.get(tx_id)
            if c in nomes:
                soma(c, nomes[c], r.currency, valor(tx_id), tx_id, contados)
            else:
                soma(None, "Sem conta informada" if c is None else "Conta de outra pessoa", r.currency, valor(tx_id), tx_id, contados)
    elif group_by == "payment_method":
        for tx_id, r in txs.items():
            forma = getattr(r.payment_method, "value", r.payment_method) or "não informada"
            soma(None, forma, r.currency, valor(tx_id), tx_id, contados)
    elif group_by == "month":
        for tx_id, r in txs.items():
            soma(None, r.billing_month or "?", r.currency, valor(tx_id), tx_id, contados)
    elif group_by == "space":
        nomes = dict(session.exec(select(Workspace.id, Workspace.name).where(Workspace.id.in_({r.workspace_id for r in linhas}))).all())
        for tx_id, r in txs.items():
            soma(r.workspace_id, nomes.get(r.workspace_id, "?"), r.currency, valor(tx_id), tx_id, contados)
    elif group_by == "title":
        exibicao: dict[str, str] = {}
        for tx_id, r in txs.items():
            chave = _normaliza_titulo(r.title)
            exibicao.setdefault(chave, re_sub_parcela(r.title))
            soma(None, exibicao[chave], r.currency, valor(tx_id), tx_id, contados)
    else:
        raise ValueError(f"agrupamento desconhecido: {group_by}")

    grupos = [Group(key=group_by, id=v[0], name=v[1], currency=v[2], amount=v[3], count=v[4]) for v in acumulado.values()]
    grupos.sort(key=lambda g: (g.currency, -g.amount, g.name))
    return grupos


def re_sub_parcela(titulo: str) -> str:
    import re

    return re.sub(r"\s*\(\d+/\d+\)\s*$", "", titulo or "").strip() or titulo
