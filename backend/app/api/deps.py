from fastapi import Depends, HTTPException
from sqlmodel import Session, select

from app.api.routes.auth import get_current_user
from app.db.session import get_session
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole, role_level


def get_workspace_membership(
    workspace_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkspaceMembership:
    """Resolve o membership do usuário no workspace da rota (404/403 se inválido)."""
    workspace = session.get(Workspace, workspace_id)
    if not workspace or workspace.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Workspace não encontrado")

    membership = session.exec(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == current_user.id,
        )
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="Você não é membro deste workspace")
    return membership


def require_role(minimum: WorkspaceRole):
    """Dependency factory: exige papel mínimo no workspace (viewer < member < admin < owner)."""
    def checker(
        membership: WorkspaceMembership = Depends(get_workspace_membership),
    ) -> WorkspaceMembership:
        if role_level(membership.role) < role_level(minimum):
            raise HTTPException(status_code=403, detail="Permissão insuficiente para esta ação")
        return membership
    return checker
