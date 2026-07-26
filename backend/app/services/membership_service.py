"""Entrada de membros num workspace — ponto único de inserção de membership.

Três fluxos criam membership (registro com convite pendente por e-mail, convite
a um usuário já existente e aceite de convite por link) e os três faziam
select-then-insert. Sob concorrência isso gerava linha duplicada, que inflava
`member_count` e — pior — fazia `get_workspace_membership` resolver o PAPEL com
`.first()` de forma não-determinística.

A barreira real é a unique `uq_membership_workspace_user`; este módulo concentra
o tratamento da colisão para os três chamadores não repetirem a mesma lógica.
"""
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models.workspace import WorkspaceMembership, WorkspaceRole


def find_membership(
    db: Session, workspace_id: int, user_id: int
) -> Optional[WorkspaceMembership]:
    return db.exec(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
        )
    ).first()


def ensure_membership(
    db: Session, workspace_id: int, user_id: int, role: WorkspaceRole
) -> bool:
    """Garante que o usuário seja membro. Devolve True se ESTA chamada criou.

    Idempotente e seguro sob concorrência: o savepoint absorve a violação da
    unique quando outra requisição inseriu a mesma membership primeiro — nesse
    caso devolve False, como se já fosse membro (que é o estado final correto).
    Não faz commit (ADR 0010): quem chama comanda a transação.
    """
    if find_membership(db, workspace_id, user_id) is not None:
        return False

    try:
        with db.begin_nested():
            db.add(WorkspaceMembership(
                workspace_id=workspace_id,
                user_id=user_id,
                role=role,
            ))
    except IntegrityError:
        # Corrida perdida: o outro caminho já criou a membership
        return False
    return True
