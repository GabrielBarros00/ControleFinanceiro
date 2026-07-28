"""Criação e leitura de notificações do usuário.

O gatilho original é o convite: adicionar alguém a um workspace sem consentimento
expunha finanças de terceiros a quem soubesse o e-mail. O convite passou a ser um
AVISO que a pessoa aceita ou recusa — e o aviso precisa chegar por dois canais
(e-mail e dentro do app), porque nem todo mundo lê e-mail.
"""
from datetime import datetime, UTC
from typing import List, Optional

from sqlmodel import Session, select

from app.models.notification import Notification, NotificationType


def notify(
    db: Session,
    *,
    user_id: int,
    type: NotificationType,
    title: str,
    body: Optional[str] = None,
    workspace_id: Optional[int] = None,
    workspace_name: Optional[str] = None,
    invite_token: Optional[str] = None,
) -> Notification:
    """Cria a notificação. Não faz commit (ADR 0010)."""
    notification = Notification(
        user_id=user_id,
        type=type,
        title=title,
        body=body,
        workspace_id=workspace_id,
        workspace_name=workspace_name,
        invite_token=invite_token,
    )
    db.add(notification)
    db.flush()
    return notification


def list_for_user(
    db: Session, user_id: int, *, only_unread: bool = False, limit: int = 50
) -> List[Notification]:
    stmt = select(Notification).where(Notification.user_id == user_id)
    if only_unread:
        stmt = stmt.where(Notification.read_at.is_(None))
    return list(
        db.exec(stmt.order_by(Notification.created_at.desc()).limit(limit)).all()
    )


def unread_count(db: Session, user_id: int) -> int:
    return len(
        db.exec(
            select(Notification.id)
            .where(Notification.user_id == user_id)
            .where(Notification.read_at.is_(None))
        ).all()
    )


def mark_read(db: Session, user_id: int, notification_id: int) -> Optional[Notification]:
    notification = db.get(Notification, notification_id)
    # A checagem de dono é o gate: notificação é pessoal e não tem workspace
    # para o require_role validar.
    if not notification or notification.user_id != user_id:
        return None
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        db.add(notification)
    return notification


def mark_all_read(db: Session, user_id: int) -> int:
    agora = datetime.now(UTC)
    pendentes = db.exec(
        select(Notification)
        .where(Notification.user_id == user_id)
        .where(Notification.read_at.is_(None))
    ).all()
    for notification in pendentes:
        notification.read_at = agora
        db.add(notification)
    return len(pendentes)


def resolve_invite_notifications(db: Session, invite_token: str) -> None:
    """Marca como lidas as notificações de um convite já resolvido.

    Sem isto, aceitar ou recusar deixava o aviso pendente para sempre — o
    contador de não lidas nunca zerava e o convite continuava "gritando".
    """
    agora = datetime.now(UTC)
    for notification in db.exec(
        select(Notification)
        .where(Notification.invite_token == invite_token)
        .where(Notification.read_at.is_(None))
    ).all():
        notification.read_at = agora
        db.add(notification)
