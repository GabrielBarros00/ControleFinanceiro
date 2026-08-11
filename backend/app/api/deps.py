from fastapi import Depends, HTTPException
from sqlmodel import Session, select

from app.api.routes.auth import get_current_user
from app.db.session import get_session
from app.models.user import PlatformRole, User, platform_level
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


def require_platform_role(minimum: PlatformRole):
    """Dependency factory: exige papel mínimo na PLATAFORMA (user < admin < superadmin).

    Eixo separado do `require_role`, e a separação é deliberada (ADR 0026):
    `require_role` pergunta "o que você pode fazer nesta casa" e é a porta dos
    dados financeiros; este pergunta "você opera este servidor" e é a porta de
    metadados, contagens e configuração. Nenhuma rota deveria precisar dos dois,
    e nenhuma rota atrás desta guarda devolve valor financeiro de terceiro — a
    política de `app.domain.access_policy` não consulta `platform_role`, então
    ser superadmin não abre um único lançamento alheio.

    404 e não 403 quando o papel falta: a existência da área administrativa não
    é informação que um usuário comum precise confirmar.
    """
    def checker(current_user: User = Depends(get_current_user)) -> User:
        if platform_level(current_user.platform_role) < platform_level(minimum):
            raise HTTPException(status_code=404, detail="Não encontrado")
        return current_user
    return checker
