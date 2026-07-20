from datetime import datetime, UTC
from typing import Optional
from sqlmodel import SQLModel, Field, UniqueConstraint


class Tag(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_tag_workspace_name"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    name: str
    color: Optional[str] = None  # hex, ex: #f59e0b

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    deleted_at: Optional[datetime] = None


class TransactionTagLink(SQLModel, table=True):
    transaction_id: int = Field(foreign_key="transaction.id", primary_key=True)
    tag_id: int = Field(foreign_key="tag.id", primary_key=True)
