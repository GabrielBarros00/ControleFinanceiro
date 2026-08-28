"""Inscrição de Web Push e preferências do aviso (ADR 0033).

Rotas PESSOAIS: o recorte é o próprio usuário, então o gate é só
`get_current_user` — não há workspace de que ser membro (ADR 0020).
"""
from typing import Optional

from fastapi import APIRouter, Depends, Header, Response, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.api.routes.auth import get_current_user
from app.core.config import settings
from app.db.session import get_session
from app.models.user import User
from app.services import push_service
from app.services.due_reminder_service import MAX_DIAS_ANTES

router = APIRouter(prefix="/me", tags=["me"])


class PushConfigRead(BaseModel):
    enabled: bool
    public_key: Optional[str] = None


class PushKeys(BaseModel):
    p256dh: str = Field(max_length=255)
    auth: str = Field(max_length=255)


class PushSubscribe(BaseModel):
    # Espelha o `PushSubscription.toJSON()` do navegador, para o cliente poder
    # mandá-lo sem remontar nada.
    endpoint: str = Field(max_length=2000)
    keys: PushKeys


class PushUnsubscribe(BaseModel):
    endpoint: str = Field(max_length=2000)


class NotificationPrefsRead(BaseModel):
    days_before: int
    by_email: bool
    show_amount: bool


class NotificationPrefsUpdate(BaseModel):
    # `ge=1`: zero dias antes seria "vence em 0 dias", que o marco "no dia" já
    # cobre melhor. O teto é o mesmo que a varredura usa para montar a janela.
    days_before: Optional[int] = Field(default=None, ge=1, le=MAX_DIAS_ANTES)
    by_email: Optional[bool] = None
    show_amount: Optional[bool] = None


@router.get("/push/config", response_model=PushConfigRead)
def get_push_config(current_user: User = Depends(get_current_user)):
    """A chave pública VAPID, ou o aviso de que push não está configurado.

    Vem por ENDPOINT e não por variável de build: girar a chave é operação de
    servidor, e exigir recompilar o frontend para isso transformaria uma troca de
    `.env` num deploy completo.
    """
    return PushConfigRead(
        enabled=push_service.push_habilitado(),
        public_key=settings.VAPID_PUBLIC_KEY if push_service.push_habilitado() else None,
    )


@router.post("/push/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
def subscribe(
    dados: PushSubscribe,
    user_agent: Optional[str] = Header(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    push_service.registrar(
        db,
        user_id=current_user.id,
        endpoint=dados.endpoint,
        p256dh=dados.keys.p256dh,
        auth=dados.keys.auth,
        # Só para a pessoa se reconhecer na lista de aparelhos. Truncado porque a
        # coluna é 255 e um User-Agent pode ser bem maior.
        user_agent=(user_agent or "")[:255] or None,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/push/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
def unsubscribe(
    dados: PushUnsubscribe,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Desativar num aparelho não desativa nos outros.

    Responde 204 mesmo quando não havia inscrição: o cliente pode ter perdido o
    registro do service worker e estar limpando por garantia, e transformar isso
    em 404 faria a tela mostrar erro num caminho que deu certo.
    """
    push_service.remover(db, user_id=current_user.id, endpoint=dados.endpoint)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/notification-preferences", response_model=NotificationPrefsRead)
def get_prefs(current_user: User = Depends(get_current_user)):
    return NotificationPrefsRead(
        days_before=current_user.notify_days_before,
        by_email=current_user.notify_by_email,
        show_amount=current_user.notify_show_amount,
    )


@router.put("/notification-preferences", response_model=NotificationPrefsRead)
def put_prefs(
    dados: NotificationPrefsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    if dados.days_before is not None:
        current_user.notify_days_before = dados.days_before
    if dados.by_email is not None:
        current_user.notify_by_email = dados.by_email
    if dados.show_amount is not None:
        current_user.notify_show_amount = dados.show_amount
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return NotificationPrefsRead(
        days_before=current_user.notify_days_before,
        by_email=current_user.notify_by_email,
        show_amount=current_user.notify_show_amount,
    )
