from datetime import datetime, UTC
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.schemas.common import NAME_MAX
from sqlmodel import Session, select

from app.api.deps import get_workspace_membership, require_role
from app.db.session import get_session
from app.services.event_service import publish_event
from app.models.category import Category
from app.models.workspace import WorkspaceMembership, WorkspaceRole

router = APIRouter(prefix="/workspaces/{workspace_id}/categories", tags=["categories"])


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_MAX)
    color: Optional[str] = None
    icon: Optional[str] = None


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=NAME_MAX)
    color: Optional[str] = None
    icon: Optional[str] = None


def _get_category_or_404(session: Session, workspace_id: int, category_id: int) -> Category:
    category = session.get(Category, category_id)
    if not category or category.workspace_id != workspace_id or category.deleted_at:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")
    return category


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
    name = category_in.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nome da categoria é obrigatório")

    # Nome único por workspace; criar com nome de categoria excluída reativa a
    # antiga em vez de bloquear para sempre (CAT-001, mesmo padrão das tags)
    existing = session.exec(
        select(Category).where(Category.workspace_id == workspace_id, Category.name == name)
    ).first()
    if existing:
        if existing.deleted_at is None:
            raise HTTPException(status_code=400, detail=f"Categoria '{name}' já existe neste workspace")
        existing.deleted_at = None
        existing.color = category_in.color
        existing.icon = category_in.icon
        existing.updated_at = datetime.now(UTC)
        session.add(existing)
        category = existing
    else:
        category = Category(
            **{**category_in.model_dump(), "name": name}, workspace_id=workspace_id
        )
        session.add(category)
    session.flush()
    publish_event(session, workspace_id, "category.created", "category", category.id, membership.user_id)
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
    category = _get_category_or_404(session, workspace_id, category_id)
    update_data = category_in.model_dump(exclude_unset=True)
    if "name" in update_data:
        name = (update_data["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Nome da categoria é obrigatório")
        clash = session.exec(
            select(Category).where(
                Category.workspace_id == workspace_id,
                Category.name == name,
                Category.deleted_at.is_(None),
            )
        ).first()
        if clash and clash.id != category.id:
            raise HTTPException(status_code=400, detail=f"Categoria '{name}' já existe neste workspace")
        update_data["name"] = name
    for key, value in update_data.items():
        setattr(category, key, value)
    category.updated_at = datetime.now(UTC)
    session.add(category)
    publish_event(session, workspace_id, "category.updated", "category", category.id, membership.user_id)
    session.commit()
    session.refresh(category)
    return category


@router.delete("/{category_id}")
def delete_category(
    workspace_id: int,
    category_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    category = _get_category_or_404(session, workspace_id, category_id)
    category.deleted_at = datetime.now(UTC)
    session.add(category)
    publish_event(session, workspace_id, "category.deleted", "category", category.id, membership.user_id)
    session.commit()
    return {"status": "ok"}
