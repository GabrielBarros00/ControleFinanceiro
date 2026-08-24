"""Notificações do usuário (não pertencem a um workspace).

Rotas de escopo PESSOAL: o destinatário de um convite ainda não é membro do
workspace, então nada aqui pode passar por `require_role` — o gate é o próprio
`user_id` da notificação.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.schemas.common import MarkAllReadRead
from app.api.routes.auth import get_current_user
from app.db.session import get_session
from app.models.notification import NotificationType
from app.models.user import User
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationRead(BaseModel):
    id: int
    type: NotificationType
    title: str
    body: Optional[str]
    workspace_id: Optional[int]
    workspace_name: Optional[str]
    invite_token: Optional[str]
    read_at: Optional[datetime]
    created_at: datetime


class NotificationList(BaseModel):
    items: List[NotificationRead]
    unread: int


@router.get("", response_model=NotificationList)
def list_notifications(
    only_unread: bool = False,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    itens = notification_service.list_for_user(
        session, current_user.id, only_unread=only_unread
    )
    return NotificationList(
        items=[NotificationRead.model_validate(n, from_attributes=True) for n in itens],
        unread=notification_service.unread_count(session, current_user.id),
    )


@router.post("/{notification_id}/read", response_model=NotificationRead)
def mark_notification_read(
    notification_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    notification = notification_service.mark_read(session, current_user.id, notification_id)
    if notification is None:
        raise HTTPException(status_code=404, detail="Notificação não encontrada")
    session.commit()
    session.refresh(notification)
    return NotificationRead.model_validate(notification, from_attributes=True)


@router.post("/read-all", response_model=MarkAllReadRead)
def mark_all_notifications_read(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    total = notification_service.mark_all_read(session, current_user.id)
    session.commit()
    return {"status": "ok", "marked": total}
