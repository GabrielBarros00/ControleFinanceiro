from datetime import datetime, UTC
from typing import Optional
from decimal import Decimal
from sqlmodel import SQLModel, Field


class Settlement(SQLModel, table=True):
    """Acerto de dívida registrado: from_user pagou amount para to_user.

    Entra no DebtService como ajuste do saldo líquido — é o que faz as
    dívidas da DebtsPage zerarem de fato.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    from_user_id: int = Field(foreign_key="user.id", index=True)  # quem pagou (devedor)
    to_user_id: int = Field(foreign_key="user.id", index=True)    # quem recebeu (credor)
    amount: Decimal = Field(decimal_places=2, max_digits=20)
    note: Optional[str] = None
    settled_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    deleted_at: Optional[datetime] = None
