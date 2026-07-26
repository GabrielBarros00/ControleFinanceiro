from datetime import datetime, UTC
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.schemas.common import NAME_MAX
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.tag import Tag, TransactionTagLink
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.api.deps import get_workspace_membership, require_role
from app.services.event_service import publish_event

router = APIRouter(prefix="/workspaces/{workspace_id}/tags", tags=["tags"])


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_MAX)
    color: Optional[str] = None


class TagUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=NAME_MAX)
    color: Optional[str] = None


class TagRead(BaseModel):
    id: int
    name: str
    color: Optional[str]


def _get_tag_or_404(session: Session, workspace_id: int, tag_id: int) -> Tag:
    tag = session.get(Tag, tag_id)
    if not tag or tag.workspace_id != workspace_id or tag.deleted_at:
        raise HTTPException(status_code=404, detail="Tag não encontrada")
    return tag


def _name_taken(session: Session, workspace_id: int, name: str, exclude_id: Optional[int] = None) -> bool:
    stmt = select(Tag).where(
        Tag.workspace_id == workspace_id,
        Tag.name == name,
        Tag.deleted_at.is_(None),
    )
    existing = session.exec(stmt).first()
    return existing is not None and existing.id != exclude_id


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
    name = tag_in.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nome da tag é obrigatório")

    # Reativação (TAG-001): criar com nome de tag excluída volta a antiga à vida
    # em vez de bloquear para sempre
    existing = session.exec(
        select(Tag).where(Tag.workspace_id == workspace_id, Tag.name == name)
    ).first()
    if existing:
        if existing.deleted_at is None:
            raise HTTPException(status_code=400, detail=f"Tag '{name}' já existe neste workspace")
        existing.deleted_at = None
        existing.color = tag_in.color
        existing.updated_at = datetime.now(UTC)
        session.add(existing)
        tag = existing
    else:
        tag = Tag(workspace_id=workspace_id, name=name, color=tag_in.color)
        session.add(tag)
    session.flush()
    publish_event(session, workspace_id, "tag.created", "tag", tag.id, membership.user_id)
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
    tag = _get_tag_or_404(session, workspace_id, tag_id)
    update_data = tag_in.model_dump(exclude_unset=True)
    if "name" in update_data:
        name = (update_data["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Nome da tag é obrigatório")
        if _name_taken(session, workspace_id, name, exclude_id=tag.id):
            raise HTTPException(status_code=400, detail=f"Tag '{name}' já existe neste workspace")
        update_data["name"] = name

    for key, value in update_data.items():
        setattr(tag, key, value)
    tag.updated_at = datetime.now(UTC)
    session.add(tag)
    publish_event(session, workspace_id, "tag.updated", "tag", tag.id, membership.user_id)
    session.commit()
    session.refresh(tag)
    return tag


@router.delete("/{tag_id}")
def delete_tag(
    workspace_id: int,
    tag_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    tag = _get_tag_or_404(session, workspace_id, tag_id)

    # Remove vínculos para a tag não continuar aparecendo nas transações
    for link in session.exec(
        select(TransactionTagLink).where(TransactionTagLink.tag_id == tag.id)
    ).all():
        session.delete(link)

    tag.deleted_at = datetime.now(UTC)
    session.add(tag)
    publish_event(session, workspace_id, "tag.deleted", "tag", tag_id, membership.user_id)
    session.commit()
    return {"status": "ok"}
