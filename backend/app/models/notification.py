from datetime import datetime, UTC
from enum import Enum
from typing import Optional

from sqlalchemy import Index
from sqlmodel import SQLModel, Field


class NotificationType(str, Enum):
    workspace_invite = "workspace_invite"   # convite para entrar num workspace
    member_added = "member_added"           # você entrou / alguém entrou
    invite_revoked = "invite_revoked"


class Notification(SQLModel, table=True):
    """Aviso destinado a UM usuário, independente de workspace.

    Existe porque convidar alguém que já tem conta ADICIONAVA a pessoa ao
    workspace sem qualquer consentimento: ela passava a ver as finanças de
    outra família sem ter aceitado nada, e sem nem saber. Agora o convite vira
    um aviso que a pessoa aceita ou recusa.

    Não tem workspace_id obrigatório de propósito: o destinatário de um convite
    ainda NÃO é membro do workspace, então a notificação não pode depender de
    permissão nele.
    """

    __table_args__ = (
        # A consulta quente é "minhas notificações não lidas, mais recentes"
        Index("ix_notification_user_created", "user_id", "created_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    type: NotificationType
    title: str
    body: Optional[str] = None

    # Contexto opcional — o workspace de origem e o recurso que a originou
    workspace_id: Optional[int] = Field(default=None, index=True)
    workspace_name: Optional[str] = None
    invite_token: Optional[str] = Field(default=None, index=True)

    read_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
