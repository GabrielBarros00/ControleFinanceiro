"""Resolução de entidades por NOME — "Nubank", "João", "Alimentação", "Casa".

O usuário fala em nomes; o banco fala em IDs. A ponte é esta, com três regras:

1. **Só entre o que a pessoa enxerga.** Cartões e contas: os dela (ADR 0021).
   Pessoas, categorias e tags: as do espaço em questão, que ela precisa integrar.
   Nome de algo de outra pessoa simplesmente não casa — nem vira sugestão.
2. **Nunca escolher sozinho.** Um casamento único resolve; dois ou mais viram
   `AMBIGUOUS` com os candidatos (`id` + nome + contexto) para o modelo PERGUNTAR
   ao usuário e repetir a chamada com o `*_id`. "Nubank" com "Nubank Gabriel" e
   "Nubank PJ" é ambíguo, sempre.
3. **Ordem de casamento**: igual (sem acento e caixa) > começa com > contém. Uma
   camada mais forte com resultado encerra a busca: "Casa" casa exatamente com
   "Casa" mesmo existindo "Casa de praia".
"""
from __future__ import annotations

import difflib
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from sqlmodel import Session, func, select

from app.mcp.errors import ErrorCode, McpToolError
from app.models.category import Category
from app.models.credit_card import CreditCard
from app.models.payment_account import PaymentAccount
from app.models.tag import Tag
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership

#: Como o usuário se refere a si mesmo numa divisão ("metade é minha").
ME_ALIASES = frozenset({"eu", "mim", "me", "comigo", "meu", "minha", "self", "i", "myself"})
MAX_CANDIDATES = 10


def norm(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto or "")
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return " ".join(sem_acento.casefold().split())


@dataclass
class Match:
    id: int
    name: str
    extra: dict[str, Any] = field(default_factory=dict)

    def candidate(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, **self.extra}


def find(query: str, items: Iterable[Match]) -> list[Match]:
    alvo = norm(query)
    if not alvo:
        return []
    itens = list(items)
    iguais = [m for m in itens if norm(m.name) == alvo]
    if iguais:
        return iguais
    comeca = [
        m for m in itens
        if norm(m.name).startswith(alvo) or any(p.startswith(alvo) for p in norm(m.name).split())
    ]
    if comeca:
        return comeca
    return [m for m in itens if alvo in norm(m.name)]


def pick(kind: str, query: str, items: Iterable[Match], *, id_param: str) -> Match:
    itens = list(items)
    achados = find(query, itens)
    if len(achados) == 1:
        return achados[0]
    if not achados:
        nomes = {norm(m.name): m for m in itens}
        parecidos = difflib.get_close_matches(norm(query), list(nomes), n=5, cutoff=0.5)
        raise McpToolError(
            ErrorCode.NOT_FOUND,
            f"Nenhum(a) {kind} encontrado(a) com o nome \"{query}\".",
            candidates=[nomes[n].candidate() for n in parecidos],
            details={"kind": kind, "query": query},
        )
    raise McpToolError(
        ErrorCode.AMBIGUOUS,
        f"Há {len(achados)} {kind}s que correspondem a \"{query}\". Pergunte ao usuário qual é "
        f"e repita a chamada informando `{id_param}`.",
        candidates=[m.candidate() for m in achados[:MAX_CANDIDATES]],
        details={"kind": kind, "query": query, "id_param": id_param},
    )


def exactly_one(value_id: Any, value_name: Any, *, field_name: str) -> None:
    if value_id is not None and value_name:
        raise McpToolError(
            ErrorCode.VALIDATION_ERROR,
            f"Informe `{field_name}` OU `{field_name}_id`, não os dois.",
        )


# --- Espaços ----------------------------------------------------------------------

@dataclass
class SpaceRef:
    workspace: Workspace
    membership: WorkspaceMembership
    member_count: int

    @property
    def id(self) -> int:
        return self.workspace.id

    @property
    def is_personal(self) -> bool:
        return self.member_count == 1


def user_spaces(session: Session, user_id: int) -> list[SpaceRef]:
    linhas = session.exec(
        select(Workspace, WorkspaceMembership)
        .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
        .where(WorkspaceMembership.user_id == user_id, Workspace.deleted_at.is_(None))
        .order_by(Workspace.name, Workspace.id)
    ).all()
    if not linhas:
        return []
    contagem = dict(session.exec(
        select(WorkspaceMembership.workspace_id, func.count())
        .where(WorkspaceMembership.workspace_id.in_([w.id for w, _ in linhas]))
        .group_by(WorkspaceMembership.workspace_id)
    ).all())
    return [SpaceRef(w, m, int(contagem.get(w.id, 1))) for w, m in linhas]


def _space_match(ref: SpaceRef) -> Match:
    return Match(ref.id, ref.workspace.name, {"members": ref.member_count, "personal": ref.is_personal})


def resolve_space(
    session: Session, user_id: int, *, space_id: Optional[int], space: Optional[str]
) -> Optional[SpaceRef]:
    """Espaço explicitamente pedido (ou `None` se nada foi informado)."""
    exactly_one(space_id, space, field_name="space")
    espacos = user_spaces(session, user_id)
    if space_id is not None:
        for ref in espacos:
            if ref.id == space_id:
                return ref
        raise McpToolError(ErrorCode.NOT_FOUND, "Espaço não encontrado.", details={"space_id": space_id})
    if space:
        escolhido = pick("espaço", space, [_space_match(r) for r in espacos], id_param="space_id")
        return next(r for r in espacos if r.id == escolhido.id)
    return None


def require_space(session: Session, user_id: int, *, space_id: Optional[int], space: Optional[str]) -> SpaceRef:
    """Espaço obrigatório: explícito, ou implícito quando a pessoa só tem um."""
    ref = resolve_space(session, user_id, space_id=space_id, space=space)
    if ref is not None:
        return ref
    espacos = user_spaces(session, user_id)
    if len(espacos) == 1:
        return espacos[0]
    raise McpToolError(
        ErrorCode.AMBIGUOUS,
        "Você participa de mais de um espaço. Pergunte ao usuário em qual e informe `space_id`.",
        candidates=[_space_match(r).candidate() for r in espacos],
        details={"kind": "espaço", "id_param": "space_id"},
    )


# --- Pessoas ----------------------------------------------------------------------

def space_members(session: Session, workspace_id: int) -> list[Match]:
    linhas = session.exec(
        select(User, WorkspaceMembership)
        .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .order_by(User.name, User.id)
    ).all()
    return [Match(u.id, u.name, {"role": getattr(m.role, "value", m.role)}) for u, m in linhas]


def is_me(name: Optional[str]) -> bool:
    return bool(name) and norm(name) in ME_ALIASES


def resolve_person(
    session: Session,
    *,
    workspace_id: int,
    me_id: int,
    person_id: Optional[int] = None,
    person: Optional[str] = None,
    members: Optional[list[Match]] = None,
) -> Match:
    exactly_one(person_id, person, field_name="person")
    membros = members if members is not None else space_members(session, workspace_id)
    if person_id is not None:
        for m in membros:
            if m.id == person_id:
                return m
        raise McpToolError(
            ErrorCode.NOT_FOUND,
            "Essa pessoa não é membro do espaço.",
            details={"person_id": person_id, "space_id": workspace_id},
        )
    if not person:
        raise McpToolError(ErrorCode.VALIDATION_ERROR, "Informe `person` (nome) ou `person_id`.")
    if is_me(person):
        for m in membros:
            if m.id == me_id:
                return m
    return pick("pessoa", person, membros, id_param="person_id")


def choose_space_for_people(
    session: Session, user_id: int, names: list[str], ids: list[int]
) -> SpaceRef:
    """Espaço implícito de uma divisão: o ÚNICO que contém todas as pessoas citadas.

    Sem ninguém além do usuário: o único espaço pessoal dele (só ele como
    membro). Qualquer outra situação é AMBIGUOUS ou NOT_FOUND — nunca um palpite.
    """
    espacos = user_spaces(session, user_id)
    outros_nomes = [n for n in names if n and not is_me(n)]
    outros_ids = [i for i in ids if i is not None and i != user_id]
    if not outros_nomes and not outros_ids:
        if len(espacos) == 1:
            return espacos[0]
        pessoais = [r for r in espacos if r.is_personal]
        if len(pessoais) == 1:
            return pessoais[0]
        raise McpToolError(
            ErrorCode.AMBIGUOUS,
            "Não está claro em qual espaço lançar. Pergunte ao usuário e informe `space_id`.",
            candidates=[_space_match(r).candidate() for r in espacos],
            details={"kind": "espaço", "id_param": "space_id"},
        )

    servem = []
    for ref in espacos:
        membros = space_members(session, ref.id)
        ids_membros = {m.id for m in membros}
        if not all(i in ids_membros for i in outros_ids):
            continue
        if all(len(find(n, membros)) == 1 for n in outros_nomes):
            servem.append(ref)
    if len(servem) == 1:
        return servem[0]
    quem = ", ".join(outros_nomes + [f"id {i}" for i in outros_ids])
    if not servem:
        raise McpToolError(
            ErrorCode.NOT_FOUND,
            f"Nenhum espaço seu tem {quem} como membro (ou o nome é ambíguo dentro do espaço). "
            "Para dividir com alguém, a pessoa precisa ser membro do espaço — o convite é feito no app.",
            details={"people": outros_nomes, "person_ids": outros_ids},
        )
    raise McpToolError(
        ErrorCode.AMBIGUOUS,
        f"{quem} participa de mais de um espaço seu. Pergunte ao usuário em qual lançar e informe `space_id`.",
        candidates=[_space_match(r).candidate() for r in servem],
        details={"kind": "espaço", "id_param": "space_id"},
    )


# --- Recursos pessoais: cartões e contas -------------------------------------------

def user_cards(session: Session, user_id: int) -> list[CreditCard]:
    return list(session.exec(
        select(CreditCard)
        .where(CreditCard.owner_user_id == user_id, CreditCard.deleted_at.is_(None))
        .order_by(CreditCard.name, CreditCard.id)
    ).all())


def resolve_card(session: Session, user_id: int, *, card_id: Optional[int], card: Optional[str]) -> Optional[CreditCard]:
    exactly_one(card_id, card, field_name="card")
    if card_id is None and not card:
        return None
    cartoes = user_cards(session, user_id)
    if card_id is not None:
        for c in cartoes:
            if c.id == card_id:
                return c
        raise McpToolError(ErrorCode.NOT_FOUND, "Cartão não encontrado.", details={"card_id": card_id})
    escolhido = pick(
        "cartão", card,
        [Match(c.id, c.name, {"closing_day": c.closing_day, "due_day": c.due_day}) for c in cartoes],
        id_param="card_id",
    )
    return next(c for c in cartoes if c.id == escolhido.id)


def user_accounts(session: Session, user_id: int, *, include_inactive: bool = False) -> list[PaymentAccount]:
    consulta = select(PaymentAccount).where(
        PaymentAccount.owner_user_id == user_id, PaymentAccount.deleted_at.is_(None)
    )
    if not include_inactive:
        consulta = consulta.where(PaymentAccount.active.is_(True))
    return list(session.exec(consulta.order_by(PaymentAccount.name, PaymentAccount.id)).all())


def resolve_account(
    session: Session, user_id: int, *, account_id: Optional[int], account: Optional[str],
    include_inactive: bool = False,
) -> Optional[PaymentAccount]:
    exactly_one(account_id, account, field_name="account")
    if account_id is None and not account:
        return None
    contas = user_accounts(session, user_id, include_inactive=include_inactive)
    if account_id is not None:
        for c in contas:
            if c.id == account_id:
                return c
        raise McpToolError(ErrorCode.NOT_FOUND, "Conta não encontrada (ou inativa).", details={"account_id": account_id})
    escolhida = pick(
        "conta", account,
        [Match(c.id, c.name, {"type": getattr(c.type, "value", c.type), "currency": c.currency}) for c in contas],
        id_param="account_id",
    )
    return next(c for c in contas if c.id == escolhida.id)


# --- Vocabulário do espaço: categorias e tags --------------------------------------

def space_categories(session: Session, workspace_id: int) -> list[Category]:
    return list(session.exec(
        select(Category)
        .where(Category.workspace_id == workspace_id, Category.deleted_at.is_(None))
        .order_by(Category.name, Category.id)
    ).all())


def resolve_category(
    session: Session, workspace_id: int, *, category_id: Optional[int], category: Optional[str]
) -> Optional[Category]:
    exactly_one(category_id, category, field_name="category")
    if category_id is None and not category:
        return None
    categorias = space_categories(session, workspace_id)
    if category_id is not None:
        for c in categorias:
            if c.id == category_id:
                return c
        raise McpToolError(ErrorCode.NOT_FOUND, "Categoria não encontrada neste espaço.", details={"category_id": category_id})
    escolhida = pick("categoria", category, [Match(c.id, c.name) for c in categorias], id_param="category_id")
    return next(c for c in categorias if c.id == escolhida.id)


def space_tags(session: Session, workspace_id: int) -> list[Tag]:
    return list(session.exec(
        select(Tag)
        .where(Tag.workspace_id == workspace_id, Tag.deleted_at.is_(None))
        .order_by(Tag.name, Tag.id)
    ).all())


def resolve_tags(session: Session, workspace_id: int, names: Optional[list[str]]) -> Optional[list[int]]:
    if names is None:
        return None
    tags = space_tags(session, workspace_id)
    itens = [Match(t.id, t.name) for t in tags]
    ids = []
    for nome in names:
        ids.append(pick("tag", nome, itens, id_param="tags (nome exato)").id)
    return list(dict.fromkeys(ids))


# --- Filtros que atravessam espaços ------------------------------------------------

def _mesmo_nome(achados: list[Match], kind: str, query: str, id_param: str) -> list[int]:
    """Em filtro, o MESMO nome em espaços diferentes é uma coisa só ("Alimentação"
    de cada casa); nomes diferentes que casam com a busca são ambiguidade."""
    if not achados:
        raise McpToolError(
            ErrorCode.NOT_FOUND, f"Nenhum(a) {kind} encontrado(a) com o nome \"{query}\".",
            details={"kind": kind, "query": query},
        )
    nomes = {norm(m.name) for m in achados}
    if len(nomes) > 1:
        raise McpToolError(
            ErrorCode.AMBIGUOUS,
            f"Há mais de um(a) {kind} que corresponde a \"{query}\". Pergunte ao usuário qual é.",
            candidates=[m.candidate() for m in achados[:MAX_CANDIDATES]],
            details={"kind": kind, "query": query, "id_param": id_param},
        )
    return sorted({m.id for m in achados})


def categories_any(
    session: Session, spaces: list[SpaceRef], *, category_id: Optional[int], category: Optional[str]
) -> Optional[list[int]]:
    exactly_one(category_id, category, field_name="category")
    if category_id is None and not category:
        return None
    itens = [
        Match(c.id, c.name, {"space_id": r.id, "space": r.workspace.name})
        for r in spaces for c in space_categories(session, r.id)
    ]
    if category_id is not None:
        if any(m.id == category_id for m in itens):
            return [category_id]
        raise McpToolError(ErrorCode.NOT_FOUND, "Categoria não encontrada.", details={"category_id": category_id})
    return _mesmo_nome(find(category, itens), "categoria", category, "category_id")


def tags_any(session: Session, spaces: list[SpaceRef], *, tag: Optional[str]) -> Optional[list[int]]:
    if not tag:
        return None
    itens = [
        Match(t.id, t.name, {"space_id": r.id, "space": r.workspace.name})
        for r in spaces for t in space_tags(session, r.id)
    ]
    return _mesmo_nome(find(tag, itens), "tag", tag, "tag")


def person_any(
    session: Session, spaces: list[SpaceRef], me_id: int, *, person_id: Optional[int], person: Optional[str]
) -> Optional[int]:
    exactly_one(person_id, person, field_name="person")
    if person_id is None and not person:
        return None
    pessoas: dict[int, Match] = {}
    for r in spaces:
        for m in space_members(session, r.id):
            pessoas.setdefault(m.id, Match(m.id, m.name))
    if person_id is not None:
        if person_id in pessoas:
            return person_id
        raise McpToolError(ErrorCode.NOT_FOUND, "Pessoa não encontrada nos seus espaços.", details={"person_id": person_id})
    if is_me(person):
        return me_id
    return pick("pessoa", person, list(pessoas.values()), id_param="person_id").id
