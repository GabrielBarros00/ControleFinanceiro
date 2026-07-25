from typing import Optional
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.workspace import WorkspaceRole, InviteStatus


class WorkspaceBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)


class WorkspaceCreate(WorkspaceBase):
    pass


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)
    # Moeda-base das agregações (ADR 0006). Existia no modelo e em toda consulta
    # desde a Onda 5, mas nenhuma rota permitia alterá-la — ficava BRL para sempre.
    base_currency: Optional[str] = Field(default=None, min_length=3, max_length=3)

    @field_validator("base_currency")
    @classmethod
    def _upper(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip().upper()
        if not v.isalpha():
            raise ValueError("Moeda-base deve ser um código ISO de 3 letras (ex.: BRL, USD)")
        return v


class WorkspaceRead(WorkspaceBase):
    id: int
    base_currency: str = "BRL"
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
