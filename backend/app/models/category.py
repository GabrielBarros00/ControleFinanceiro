from datetime import datetime, UTC
from typing import Optional
from sqlmodel import SQLModel, Field


class CategoryBase(SQLModel):
    name: str = Field(index=True)
    color: Optional[str] = Field(default=None)  # hex, ex: #22c55e
    icon: Optional[str] = Field(default=None)   # nome do ícone (lucide)


class Category(CategoryBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    deleted_at: Optional[datetime] = Field(default=None)
