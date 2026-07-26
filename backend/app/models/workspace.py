import secrets
from datetime import datetime, UTC
from enum import Enum
from typing import Optional, List

from sqlalchemy import Column, Index, Integer, String
from sqlmodel import SQLModel, Field, Relationship


class WorkspaceRole(str, Enum):
    owner = "owner"
    admin = "admin"
    member = "member"
    viewer = "viewer"


_ROLE_LEVELS = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}


def role_level(role) -> int:
    """Nível hierárquico de um papel (aceita enum ou string vinda do banco)."""
    value = role.value if isinstance(role, WorkspaceRole) else str(role)
    return _ROLE_LEVELS.get(value, -1)


class InviteStatus(str, Enum):
    pending = "pending"
    accepted = "accepted"
    revoked = "revoked"


class Workspace(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    description: Optional[str] = None
    created_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    # Moeda-base das agregações (ADR 0006): transações em outra moeda ficam FORA
    # dos totais até existir taxa histórica congelada
    base_currency: str = Field(
        default="BRL",
        sa_column=Column(String(3), nullable=False, server_default="BRL"),
    )
    # Sequência monotônica de eventos de sincronização (WebSocket/resync)
    event_seq: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    deleted_at: Optional[datetime] = Field(default=None)

    memberships: List["WorkspaceMembership"] = Relationship(back_populates="workspace")


class WorkspaceMembership(SQLModel, table=True):
    # uq(workspace, user): um usuário tem UM papel por workspace. Três caminhos
    # inserem membership (registro com convite pendente, convite a usuário
    # existente e aceite de link) e todos faziam select-then-insert: sob
    # concorrência nascia linha duplicada, que inflava member_count e — pior —
    # fazia get_workspace_membership resolver o PAPEL com .first(), de forma
    # não-determinística.
    __table_args__ = (
        Index("uq_membership_workspace_user", "workspace_id", "user_id", unique=True),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id")
    user_id: int = Field(foreign_key="user.id")
    role: WorkspaceRole = Field(
        default=WorkspaceRole.member,
        sa_column=Column(String(20), nullable=False, server_default="member"),
    )

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    workspace: Workspace = Relationship(back_populates="memberships")


class WorkspaceInvite(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    # email=None indica convite por link (qualquer usuário logado pode aceitar)
    email: Optional[str] = Field(default=None, index=True)
    role: WorkspaceRole = Field(
        default=WorkspaceRole.member,
        sa_column=Column(String(20), nullable=False, server_default="member"),
    )
    token: str = Field(
        default_factory=lambda: secrets.token_urlsafe(32),
        unique=True,
        index=True,
    )
    invited_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    status: InviteStatus = Field(
        default=InviteStatus.pending,
        sa_column=Column(String(20), nullable=False, server_default="pending"),
    )
    expires_at: datetime
    max_uses: Optional[int] = Field(default=None)  # apenas convites por link
    uses: int = Field(default=0)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
