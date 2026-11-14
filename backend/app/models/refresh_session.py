from datetime import datetime, UTC
from typing import Optional

from sqlalchemy import DateTime
from sqlmodel import SQLModel, Field


class RefreshSession(SQLModel, table=True):
    """Sessão de refresh persistida (SEC-004): permite revogar no logout e
    rotacionar a cada refresh, com detecção de reuso por família.

    Cada refresh token carrega um `jti` (esta linha) e um `family` (a cadeia de
    rotações da mesma sessão). Reapresentar um jti já rotacionado (revoked)
    denuncia roubo → a família inteira é revogada — salvo logo depois da
    rotação, com a sucessora viva (ADR 0042).
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    jti: str = Field(unique=True, index=True)
    family_id: str = Field(index=True)
    expires_at: datetime = Field(sa_type=DateTime)
    revoked_at: Optional[datetime] = Field(default=None, sa_type=DateTime)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), sa_type=DateTime)
