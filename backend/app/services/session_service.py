"""Sessões de refresh persistidas com rotação e detecção de reuso (SEC-004)."""
import uuid
from datetime import datetime, timedelta, UTC
from typing import Optional, Tuple

from sqlmodel import Session, select

from app.core.config import settings
from app.core.jwt import create_refresh_token, decode_token
from app.models.refresh_session import RefreshSession


class SessionError(Exception):
    """Refresh inválido/expirado/reutilizado (o chamador traduz para 401)."""


def _new_refresh(db: Session, user_id: int, family_id: str) -> str:
    jti = uuid.uuid4().hex
    expires_at = datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRES_DAYS)
    db.add(RefreshSession(
        user_id=user_id, jti=jti, family_id=family_id, expires_at=expires_at,
    ))
    return create_refresh_token(data={"sub": str(user_id), "jti": jti, "family": family_id})


def start_session(db: Session, user_id: int) -> str:
    """Nova sessão (login/registro/OAuth): nova família + jti persistidos."""
    return _new_refresh(db, user_id, uuid.uuid4().hex)


def _revoke_family(db: Session, family_id: str) -> None:
    for s in db.exec(
        select(RefreshSession).where(
            RefreshSession.family_id == family_id,
            RefreshSession.revoked_at.is_(None),
        )
    ).all():
        s.revoked_at = datetime.now(UTC)
        db.add(s)


def rotate_session(db: Session, refresh_token: str) -> Tuple[int, str]:
    """Valida o refresh e devolve (user_id, novo_refresh_token), rotacionando.

    - jti desconhecido → inválido;
    - jti já revogado → REUSO: revoga a família inteira;
    - expirado → inválido;
    - token legado (sem jti) → aceita e migra para uma sessão gerenciada.
    """
    try:
        payload = decode_token(refresh_token)
        if payload.get("token_type") != "refresh":
            raise SessionError("tipo inválido")
        user_id = int(payload["sub"])
    except SessionError:
        raise
    except Exception:
        raise SessionError("token inválido")

    jti = payload.get("jti")
    family = payload.get("family")
    if not jti or not family:
        # Legado (pré-SEC-004): sem sessão persistida — inicia uma gerenciada
        return user_id, start_session(db, user_id)

    session = db.exec(select(RefreshSession).where(RefreshSession.jti == jti)).first()
    if session is None:
        raise SessionError("sessão desconhecida")
    if session.revoked_at is not None:
        # Reuso de um jti já rotacionado → roubo: derruba a família toda
        _revoke_family(db, session.family_id)
        raise SessionError("sessão reutilizada")
    now = datetime.now(UTC)
    exp = session.expires_at
    if exp.tzinfo is None:  # SQLite devolve datetime naive
        now = now.replace(tzinfo=None)
    if exp < now:
        raise SessionError("sessão expirada")

    # Rotação: revoga o atual e emite o próximo na mesma família
    session.revoked_at = datetime.now(UTC)
    db.add(session)
    return user_id, _new_refresh(db, user_id, session.family_id)


def revoke_session(db: Session, refresh_token: Optional[str]) -> None:
    """Logout: revoga a sessão do token (best-effort — cookie pode estar velho)."""
    if not refresh_token:
        return
    try:
        payload = decode_token(refresh_token)
        jti = payload.get("jti")
    except Exception:
        return
    if not jti:
        return
    session = db.exec(select(RefreshSession).where(RefreshSession.jti == jti)).first()
    if session and session.revoked_at is None:
        session.revoked_at = datetime.now(UTC)
        db.add(session)
