"""As conexões de IA de uma pessoa, do jeito que a tela "Integrações com IA" as mostra."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, UTC
from typing import List, Optional
from urllib.parse import urlsplit

from sqlalchemy import func
from sqlmodel import Session, select

from app.models.oauth import OAuthClient, OAuthGrant, OAuthToken
from app.services.oauth import scopes as escopos, tokens


def _agora() -> datetime:
    return datetime.now(UTC)


def _aware(momento: Optional[datetime]) -> Optional[datetime]:
    if momento is None:
        return None
    return momento if momento.tzinfo else momento.replace(tzinfo=UTC)


@dataclass
class ConnectionView:
    grant_id: int
    client_name: str
    client_kind: str
    client_host: Optional[str]
    redirect_host: Optional[str]
    scopes: List[str]
    created_at: datetime
    last_used_at: Optional[datetime]
    #: `active` | `expired` (sem refresh vivo: o cliente precisa reconectar) | `revoked`
    status: str
    revoked_at: Optional[datetime]


def _host(uri: Optional[str]) -> Optional[str]:
    if not uri:
        return None
    try:
        return urlsplit(uri).hostname
    except ValueError:
        return None


def list_connections(session: Session, user_id: int, *, include_revoked: bool = False) -> List[ConnectionView]:
    consulta = select(OAuthGrant, OAuthClient).join(OAuthClient, OAuthClient.id == OAuthGrant.client_pk).where(
        OAuthGrant.user_id == user_id
    )
    if not include_revoked:
        consulta = consulta.where(OAuthGrant.revoked_at.is_(None))
    linhas = session.exec(consulta.order_by(OAuthGrant.created_at.desc())).all()
    if not linhas:
        return []

    # Validade do refresh mais novo de cada conexão: sem refresh vivo e sem
    # access vivo, a conexão existe mas o cliente não consegue mais usá-la.
    ids = [g.id for g, _ in linhas]
    vivos = dict(session.exec(
        select(OAuthToken.grant_id, func.max(OAuthToken.expires_at))
        .where(
            OAuthToken.grant_id.in_(ids),
            OAuthToken.revoked_at.is_(None),
            OAuthToken.rotated_at.is_(None),
        )
        .group_by(OAuthToken.grant_id)
    ).all())

    agora = _agora()
    resultado = []
    for concessao, cliente in linhas:
        if concessao.revoked_at is not None:
            estado = "revoked"
        else:
            validade = _aware(vivos.get(concessao.id))
            estado = "active" if validade is not None and validade > agora else "expired"
        resultado.append(ConnectionView(
            grant_id=concessao.id,
            client_name=concessao.client_name,
            client_kind=cliente.kind,
            client_host=_host(cliente.client_id) if cliente.kind == "cimd" else _host(cliente.client_uri),
            redirect_host=_host(cliente.redirect_uris[0]) if cliente.redirect_uris else None,
            scopes=escopos.split(concessao.scopes),
            created_at=_aware(concessao.created_at),
            last_used_at=_aware(concessao.last_used_at),
            status=estado,
            revoked_at=_aware(concessao.revoked_at),
        ))
    return resultado


def revoke_connection(session: Session, user_id: int, grant_id: int) -> bool:
    """Revoga UMA conexão da própria pessoa. `False` = não é dela (a rota responde 404)."""
    concessao = session.get(OAuthGrant, grant_id)
    if concessao is None or concessao.user_id != user_id:
        return False
    tokens.revoke_grant(session, concessao, "user")
    return True
