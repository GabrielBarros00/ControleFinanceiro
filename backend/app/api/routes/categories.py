from typing import List

from fastapi import APIRouter, Depends

from app.schemas.common import StatusRead
from sqlmodel import Session, select

from app.api.deps import get_workspace_membership, require_role
from app.db.session import get_session
from app.models.category import Category
from app.models.workspace import WorkspaceMembership, WorkspaceRole

from app.schemas.category import CategoryCreate, CategoryUpdate
from app.services.commands import planning as plan_cmd

router = APIRouter(prefix="/workspaces/{workspace_id}/categories", tags=["categories"])


@router.get("", response_model=List[Category])
def list_categories(
    workspace_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    return session.exec(
        select(Category).where(
            Category.workspace_id == workspace_id,
            Category.deleted_at.is_(None),
        ).order_by(Category.name)
    ).all()


@router.post("", response_model=Category)
def create_category(
    workspace_id: int,
    category_in: CategoryCreate,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    category = plan_cmd.create_category(session, workspace_id, category_in, membership)
    session.commit()
    session.refresh(category)
    return category


@router.put("/{category_id}", response_model=Category)
def update_category(
    workspace_id: int,
    category_id: int,
    category_in: CategoryUpdate,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    category = plan_cmd.update_category(session, workspace_id, category_id, category_in, membership)
    session.commit()
    session.refresh(category)
    return category


@router.delete("/{category_id}", response_model=StatusRead)
def delete_category(
    workspace_id: int,
    category_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    plan_cmd.delete_category(session, workspace_id, category_id, membership)
    session.commit()
    return {"status": "ok"}
