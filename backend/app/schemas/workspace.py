from typing import Optional
from datetime import datetime
from pydantic import BaseModel, EmailStr

from app.models.workspace import WorkspaceRole, InviteStatus


class WorkspaceBase(BaseModel):
    name: str
    description: Optional[str] = None


class WorkspaceCreate(WorkspaceBase):
    pass


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class WorkspaceRead(WorkspaceBase):
    id: int
    created_at: datetime
    updated_at: datetime
    # Quem criou/é dono e quantos membros — para o switcher indicar "de quem é"
    # quando o workspace é compartilhado (member_count > 1)
    owner_user_id: Optional[int] = None
    owner_name: Optional[str] = None
    member_count: int = 1


class MemberRead(BaseModel):
    user_id: int
    role: WorkspaceRole
    user_name: str
    user_email: str
    joined_at: datetime


class MemberUpdate(BaseModel):
    role: WorkspaceRole


class InviteCreate(BaseModel):
    email: EmailStr
    role: WorkspaceRole = WorkspaceRole.member


class InviteLinkCreate(BaseModel):
    role: WorkspaceRole = WorkspaceRole.member
    expires_days: int = 7
    max_uses: Optional[int] = None


class InviteRead(BaseModel):
    id: int
    workspace_id: int
    email: Optional[str]
    role: WorkspaceRole
    status: InviteStatus
    expires_at: datetime
    max_uses: Optional[int]
    uses: int
    created_at: datetime


class InviteLinkRead(InviteRead):
    token: str
    url: str


class InviteInfoRead(BaseModel):
    """Informações públicas (para usuário logado) de um convite por token."""
    workspace_name: str
    role: WorkspaceRole
    invited_by: Optional[str]
    valid: bool
    reason: Optional[str] = None
