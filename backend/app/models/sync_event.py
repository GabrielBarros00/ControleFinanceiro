from datetime import datetime, UTC
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import SQLModel, Field


class SyncEvent(SQLModel, table=True):
    """Evento de sincronização por workspace, com sequência monotônica.

    O par (workspace_id, seq) permite que clientes detectem lacunas
    (eventos perdidos) e disparem um resync completo.
    """
    __table_args__ = (UniqueConstraint("workspace_id", "seq", name="uq_syncevent_workspace_seq"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    seq: int
    event_type: str  # ex: "transaction.created"
    resource_type: Optional[str] = None
    resource_id: Optional[int] = None
    actor_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
