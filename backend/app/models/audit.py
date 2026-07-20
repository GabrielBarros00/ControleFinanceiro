from datetime import datetime, UTC
from enum import Enum
from typing import Optional, Dict, Any
from sqlmodel import SQLModel, Field, JSON

class ActionType(str, Enum):
    create = "create"
    update = "update"
    delete = "delete"
    login = "login"
    logout = "logout"

class AuditLogBase(SQLModel):
    action: ActionType
    resource_type: Optional[str] = Field(default=None, index=True) # Ex: 'Transaction', 'Workspace'
    resource_id: Optional[int] = Field(default=None, index=True)
    old_values: Optional[Dict[str, Any]] = Field(default=None, sa_type=JSON)
    new_values: Optional[Dict[str, Any]] = Field(default=None, sa_type=JSON)
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

class AuditLog(AuditLogBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    # workspace_id (AUD-001): permite consultar a trilha por workspace sem
    # varrer todos os recursos. Preenchido pelos listeners a partir do alvo.
    # SEM FK de propósito: a trilha é histórica e PRECISA sobreviver à exclusão do
    # recurso auditado — inclusive do próprio Workspace (auditar o DELETE de um
    # workspace referenciaria a linha recém-apagada e violaria a FK sob Postgres).
    # A migração b8e3f105c7a9 já cria a coluna sem FK; o modelo agora reflete isso.
    workspace_id: Optional[int] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
