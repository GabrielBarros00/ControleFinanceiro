from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field

from app.schemas.common import NormalizedEmail, OptionalCurrencyCode

from app.models.workspace import WorkspaceRole, InviteStatus


class WorkspaceBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)


class WorkspaceCreate(WorkspaceBase):
    # Moeda-base já na criação. Sem este campo todo workspace nascia "BRL" e a
    # única forma de mudar era o PUT, que dispara a reconversão de TODO o
    # histórico (BaseCurrencyService) — uma operação pesada e sujeita a
    # `MissingRates` para um workspace ainda vazio.
    base_currency: OptionalCurrencyCode = None


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)
    # Moeda-base das agregações (ADR 0006). Existia no modelo e em toda consulta
    # desde a Onda 5, mas nenhuma rota permitia alterá-la — ficava BRL para sempre.
    # Mesma validação de todo campo de moeda do app (`isalpha()` sozinho aceitava
    # "ÁÁÁ", que viraria uma moeda-base impossível de casar com qualquer cotação).
    base_currency: OptionalCurrencyCode = None


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
    email: NormalizedEmail
    role: WorkspaceRole = WorkspaceRole.member


class InviteLinkCreate(BaseModel):
    role: WorkspaceRole = WorkspaceRole.member
    # Validação no SCHEMA (antes `expires_days` era conferido na rota e
    # `max_uses` não era conferido em lugar nenhum: `max_uses=0` criava um link
    # JÁ esgotado, porque o gate é `uses >= max_uses` → 0 >= 0).
    expires_days: int = Field(default=7, ge=1, le=30)
    max_uses: Optional[int] = Field(default=None, ge=1)


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
