from datetime import datetime, UTC
from typing import List

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.schemas.workspace import WorkspaceCreate, WorkspaceRead, WorkspaceUpdate
from app.api.routes.auth import get_current_user
from app.api.deps import get_workspace_membership, require_role
from app.services.category_service import seed_default_categories
from app.services.event_service import publish_event

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.post("/", response_model=WorkspaceRead)
def create_workspace(
    *,
    session: Session = Depends(get_session),
    workspace_in: WorkspaceCreate,
    current_user: User = Depends(get_current_user)
):
    workspace = Workspace(
        name=workspace_in.name,
        description=workspace_in.description,
        created_by_user_id=current_user.id
    )
    session.add(workspace)
    session.commit()
    session.refresh(workspace)

    membership = WorkspaceMembership(
        workspace_id=workspace.id,
        user_id=current_user.id,
        role=WorkspaceRole.owner
    )
    session.add(membership)
    seed_default_categories(session, workspace.id)
    session.commit()

    return workspace


@router.get("/", response_model=List[WorkspaceRead])
def list_workspaces(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    statement = (
        select(Workspace)
        .join(WorkspaceMembership)
        .where(
            WorkspaceMembership.user_id == current_user.id,
            Workspace.deleted_at.is_(None),
        )
    )
    workspaces = session.exec(statement).all()
    return workspaces


@router.get("/{workspace_id}", response_model=WorkspaceRead)
def get_workspace(
    workspace_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    return session.get(Workspace, workspace_id)


@router.put("/{workspace_id}", response_model=WorkspaceRead)
def update_workspace(
    workspace_id: int,
    workspace_in: WorkspaceUpdate,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.admin)),
):
    workspace = session.get(Workspace, workspace_id)
    for key, value in workspace_in.model_dump(exclude_unset=True).items():
        setattr(workspace, key, value)
    workspace.updated_at = datetime.now(UTC)
    session.add(workspace)
    publish_event(session, workspace_id, "workspace.updated", "workspace", workspace_id, membership.user_id)
    session.commit()
    session.refresh(workspace)
    return workspace


@router.delete("/{workspace_id}")
def delete_workspace(
    workspace_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.owner)),
):
    workspace = session.get(Workspace, workspace_id)
    workspace.deleted_at = datetime.now(UTC)
    session.add(workspace)
    publish_event(session, workspace_id, "workspace.deleted", "workspace", workspace_id, membership.user_id)
    session.commit()
    return {"status": "ok"}
