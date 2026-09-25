from typing import List

from fastapi import APIRouter, Depends

from app.schemas.common import StatusRead
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.tag import Tag
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.api.deps import get_workspace_membership, require_role
from app.schemas.tag import TagCreate, TagRead, TagUpdate
from app.services.commands import planning as plan_cmd

router = APIRouter(prefix="/workspaces/{workspace_id}/tags", tags=["tags"])


@router.get("", response_model=List[TagRead])
def list_tags(
    workspace_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    return session.exec(
        select(Tag)
        .where(Tag.workspace_id == workspace_id)
        .where(Tag.deleted_at.is_(None))
        .order_by(Tag.name)
    ).all()


@router.post("", response_model=TagRead)
def create_tag(
    workspace_id: int,
    tag_in: TagCreate,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    tag = plan_cmd.create_tag(session, workspace_id, tag_in, membership)
    session.commit()
    session.refresh(tag)
    return tag


@router.put("/{tag_id}", response_model=TagRead)
def update_tag(
    workspace_id: int,
    tag_id: int,
    tag_in: TagUpdate,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    tag = plan_cmd.update_tag(session, workspace_id, tag_id, tag_in, membership)
    session.commit()
    session.refresh(tag)
    return tag


@router.delete("/{tag_id}", response_model=StatusRead)
def delete_tag(
    workspace_id: int,
    tag_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    plan_cmd.delete_tag(session, workspace_id, tag_id, membership)
    session.commit()
    return {"status": "ok"}
