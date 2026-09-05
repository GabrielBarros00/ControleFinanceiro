"""Busca global: "onde foi aquele pagamento do dentista?".

## A pergunta que o app não respondia

O produto tem cinco listas (lançamentos por espaço, rendas, acertos, faturas,
extrato) e nenhuma delas atravessa as outras. Achar um lançamento de três meses
atrás exigia lembrar em qual espaço ele foi, abrir a tela certa, navegar até o
mês certo e então filtrar. Quem não lembra o mês não tem caminho nenhum.

## O ponto delicado: uma consulta que atravessa TODAS as listas

Cada lista tem hoje o seu filtro de visibilidade (ADR 0018), aplicado no
`select` que a monta. Uma rota que varre tudo é o lugar clássico de esquecer
esse filtro — e o efeito não é uma tela errada, é um membro restrito lendo o
título de uma despesa que a lista de lançamentos esconde dele.

Por isso aqui **nada é consultado sem o predicado da lista de origem**:

- lançamento → `transaction_scope(membership)`, o MESMO de `transactions.py`,
  aplicado espaço a espaço com o membership daquele espaço;
- renda → `Income.user_id == eu` (renda é pessoal, ADR 0021);
- acerto → só aqueles em que eu sou uma das pontas;
- fatura → só de cartão meu (`owner_user_id`), que é como `me_cards` faz.

`tests/security/test_busca_respeita_visibilidade.py` tranca cada uma dessas
linhas, e foi escrito antes desta rota existir.

## O que ela NÃO é

Não é busca com relevância, correção ortográfica ou índice invertido. É `LIKE`
em título, com teto de resultados por tipo. O objetivo é achar o que se sabe que
existe — e para isso o `LIKE` basta, com a vantagem de não introduzir um índice
que precise ser mantido em sincronia com o dado.
"""
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_
from sqlmodel import Session, select

from app.api.routes.auth import get_current_user
from app.db.session import get_session
from app.domain.access_policy import transaction_scope
from app.models.credit_card import CreditCard
from app.models.income import Income
from app.models.settlement import Settlement
from app.models.transaction import Transaction
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.schemas.search import SearchGroup, SearchHit, SearchRead

router = APIRouter(prefix="/me/search", tags=["me-search"])

#: Teto POR TIPO. A busca é um atalho, não uma listagem: quem precisa de tudo
#: tem a tela da lista, com filtro e paginação de verdade.
LIMITE_POR_TIPO = 8


def _como(termo: str):
    """`LIKE` com escape e caixa normalizada nos DOIS lados.

    `%` e `_` são curingas: sem `autoescape`, buscar "%" casaria com tudo. E o
    `lower()` dos dois lados existe porque o `LIKE` é sensível à caixa no
    Postgres e insensível no SQLite — sem ele, "dentista" acharia "Dentista" em
    desenvolvimento e não acharia em produção, que é o pior tipo de divergência.
    """
    return lambda coluna: func.lower(coluna).contains(termo.lower(), autoescape=True)


@router.get("", response_model=SearchRead)
@router.get("/", response_model=SearchRead, include_in_schema=False)
def buscar(
    q: str = Query(..., min_length=2, max_length=80, description="Termo de busca"),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> SearchRead:
    casa = _como(q)
    grupos: List[SearchGroup] = []

    # --- Lançamentos, espaço a espaço -------------------------------------
    #
    # Espaço a espaço, e não numa consulta só, porque o predicado de
    # visibilidade DEPENDE do membership naquele espaço: a mesma pessoa pode ter
    # acesso completo numa casa e ser restrita noutra. Uma consulta única com um
    # `or_` de espaços aplicaria o mesmo recorte aos dois — e o recorte errado
    # aqui é vazamento, não desconforto.
    memberships = session.exec(
        select(WorkspaceMembership).where(WorkspaceMembership.user_id == user.id)
    ).all()
    nomes = {
        w.id: w.name
        for w in session.exec(
            select(Workspace).where(
                Workspace.id.in_([m.workspace_id for m in memberships] or [-1])
            )
        ).all()
    }

    lancamentos: List[SearchHit] = []
    for m in memberships:
        achados = session.exec(
            select(Transaction)
            .where(Transaction.workspace_id == m.workspace_id)
            .where(Transaction.deleted_at.is_(None))
            .where(casa(Transaction.title))
            .where(transaction_scope(m))
            .order_by(Transaction.transaction_date.desc())
            .limit(LIMITE_POR_TIPO)
        ).all()
        for t in achados:
            lancamentos.append(SearchHit(
                kind="transaction",
                id=t.id,
                title=t.title,
                amount=t.total_amount,
                currency=t.currency,
                occurred_on=t.transaction_date.date(),
                workspace_id=m.workspace_id,
                workspace_name=nomes.get(m.workspace_id),
                href=f"/w/{m.workspace_id}/transactions?q={t.title}",
            ))
    lancamentos.sort(key=lambda h: h.occurred_on, reverse=True)
    if lancamentos:
        grupos.append(SearchGroup(
            kind="transaction", label="Lançamentos", items=lancamentos[:LIMITE_POR_TIPO],
        ))

    # --- Rendas (pessoais, ADR 0021) --------------------------------------
    rendas = session.exec(
        select(Income)
        .where(Income.user_id == user.id)
        .where(casa(Income.title))
        .order_by(Income.received_at.desc())
        .limit(LIMITE_POR_TIPO)
    ).all()
    if rendas:
        grupos.append(SearchGroup(kind="income", label="Rendas", items=[
            SearchHit(
                kind="income", id=r.id, title=r.title, amount=r.amount,
                currency=r.currency, occurred_on=r.received_at.date(),
                href="/me/income",
            )
            for r in rendas
        ]))

    # --- Acertos em que EU sou uma das pontas -----------------------------
    acertos = session.exec(
        select(Settlement)
        .where(or_(
            Settlement.from_user_id == user.id,
            Settlement.to_user_id == user.id,
        ))
        .where(casa(Settlement.note))
        .order_by(Settlement.created_at.desc())
        .limit(LIMITE_POR_TIPO)
    ).all()
    if acertos:
        grupos.append(SearchGroup(kind="settlement", label="Acertos", items=[
            SearchHit(
                kind="settlement", id=a.id, title=a.note or "Acerto",
                amount=a.amount, currency=None,
                occurred_on=a.created_at.date() if a.created_at else None,
                workspace_id=a.workspace_id,
                workspace_name=nomes.get(a.workspace_id),
                href="/me/settlements",
            )
            for a in acertos
        ]))

    # --- Cartões meus -----------------------------------------------------
    cartoes = session.exec(
        select(CreditCard)
        .where(CreditCard.owner_user_id == user.id)
        .where(casa(CreditCard.name))
        .limit(LIMITE_POR_TIPO)
    ).all()
    if cartoes:
        grupos.append(SearchGroup(kind="card", label="Cartões", items=[
            SearchHit(
                kind="card", id=c.id, title=c.name, amount=None,
                currency=c.currency, occurred_on=None, href="/me/cards",
            )
            for c in cartoes
        ]))

    return SearchRead(query=q, groups=grupos, total=sum(len(g.items) for g in grupos))
