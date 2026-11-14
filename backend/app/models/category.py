from datetime import datetime, UTC
from typing import Optional
from sqlalchemy import DateTime, Index
from sqlmodel import SQLModel, Field


class CategoryBase(SQLModel):
    name: str = Field(index=True)
    color: Optional[str] = Field(default=None)  # hex, ex: #22c55e
    icon: Optional[str] = Field(default=None)   # nome do ícone (lucide)


class Category(CategoryBase, table=True):
    # Nome único por workspace, como Tag e PaymentAccount já eram. A checagem
    # em Python sozinha não sobrevive a duas requisições simultâneas.
    __table_args__ = (
        Index("uq_category_workspace_name", "workspace_id", "name", unique=True),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), sa_type=DateTime)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), sa_type=DateTime)
    deleted_at: Optional[datetime] = Field(default=None, sa_type=DateTime)
