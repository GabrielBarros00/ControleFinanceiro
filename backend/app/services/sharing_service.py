"""Compartilhamento de recurso PESSOAL com workspaces (ADR 0019).

Renda, cartão, conta de pagamento e financiamento seguem a mesma forma: pertencem
a uma pessoa e podem ser oferecidos, explicitamente, ao orçamento de um ou mais
workspaces dela. Cada domínio tem sua tabela de vínculo (FKs reais, não uma tabela
polimórfica), mas a MECÂNICA é uma só — e mora aqui, para não existirem quatro
implementações que divergem na próxima mudança.

Duas invariantes que as quatro compartilham:

1. **Só compartilho com workspace de que eu participo.** Sem isso, mandar um
   `workspace_id` arbitrário no corpo faria minha renda aparecer no orçamento da
   casa de um desconhecido — uma escrita cruzada de workspace, que é exatamente o
   que o `test_idor_scan` existe para impedir.
2. **A lista enviada é o estado final.** O que não vem na lista é revogado, então
   deixar de compartilhar é a mesma operação de compartilhar, sem endpoint extra.
"""
from typing import Iterable, List

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models.workspace import WorkspaceMembership


def workspaces_do_usuario(session: Session, user_id: int) -> set:
    """Ids dos workspaces em que o usuário é membro."""
    return set(
        session.exec(
            select(WorkspaceMembership.workspace_id).where(
                WorkspaceMembership.user_id == user_id
            )
        ).all()
    )


def share_ids(session: Session, share_model, fk_column, resource_id: int) -> List[int]:
    """Workspaces com que o recurso está compartilhado hoje."""
    if resource_id is None:
        return []
    return list(
        session.exec(
            select(share_model.workspace_id).where(fk_column == resource_id)
        ).all()
    )


def set_shares(
    session: Session,
    share_model,
    fk_name: str,
    resource_id: int,
    workspace_ids: Iterable[int],
    *,
    user_id: int,
) -> None:
    """Deixa o compartilhamento do recurso IGUAL à lista pedida.

    Não faz commit (ADR 0010): quem chama comanda a transação.
    """
    desejados = set(workspace_ids or [])
    if desejados:
        permitidos = workspaces_do_usuario(session, user_id)
        invasores = desejados - permitidos
        if invasores:
            raise HTTPException(
                status_code=400,
                detail="Você só pode compartilhar com workspaces de que participa",
            )

    fk_column = getattr(share_model, fk_name)
    atuais = {
        linha.workspace_id: linha
        for linha in session.exec(select(share_model).where(fk_column == resource_id)).all()
    }

    for workspace_id in desejados - set(atuais):
        session.add(share_model(**{fk_name: resource_id, "workspace_id": workspace_id}))
    for workspace_id in set(atuais) - desejados:
        session.delete(atuais[workspace_id])
