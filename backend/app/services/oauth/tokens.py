"""Tokens e concessões: emitir, renovar, verificar, revogar.

**Refresh rotaciona a cada uso** (OAuth 2.1 §4.3.1, obrigatório para cliente
público): a renovação marca o refresh antigo como `rotated_at` com um UPDATE
condicional e emite um par novo. Um refresh já rotacionado que reaparece só pode
ser cópia — do cliente legítimo ou de quem o roubou, e não há como saber qual —,
então a concessão INTEIRA cai e a pessoa reconecta. É a mesma regra das sessões
do app (ADR 0013).

**Access é conferido no banco a cada chamada.** Não é JWT de propósito: a
revogação ("Desconectar" na tela, troca de senha, conta desativada) precisa valer
na próxima tool call, não daqui a uma hora.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, UTC
from typing import List, Optional
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import update
from sqlmodel import Session, select

from app.core.config import settings
from app.models.oauth import OAuthClient, OAuthGrant, OAuthToken
from app.models.user import User
from app.services.oauth import crypto, scopes as escopos
from app.services.oauth.errors import OAuthError


def _agora() -> datetime:
    return datetime.now(UTC)


def _aware(momento: Optional[datetime]) -> Optional[datetime]:
    if momento is None:
        return None
    return momento if momento.tzinfo else momento.replace(tzinfo=UTC)


def _normaliza_recurso(valor: str) -> str:
    partes = urlsplit(valor.strip())
    caminho = partes.path.rstrip("/")
    return urlunsplit((partes.scheme.lower(), partes.netloc.lower(), caminho, partes.query, ""))


def same_resource(valor: Optional[str]) -> bool:
    """O `resource` pedido (RFC 8707) identifica ESTE servidor MCP?

    Aceita a URI canônica (`<origem>/mcp`) e a origem pura: o authorization
    server só emite para um recurso, então os dois designam a mesma audiência — o
    que se recusa é um recurso de OUTRO lugar, que é o ataque que a indicação de
    recurso existe para barrar.
    """
    if not valor:
        return True
    try:
        pedido = _normaliza_recurso(valor)
    except ValueError:
        return False
    return pedido in {
        _normaliza_recurso(settings.mcp_resource_url),
        _normaliza_recurso(settings.oauth_issuer),
    }


@dataclass
class TokenPair:
    access_token: str
    refresh_token: Optional[str]
    expires_in: int
    scope: str

    def body(self) -> dict:
        corpo = {
            "access_token": self.access_token,
            "token_type": "Bearer",
            "expires_in": self.expires_in,
            "scope": self.scope,
        }
        if self.refresh_token:
            corpo["refresh_token"] = self.refresh_token
        return corpo


@dataclass(frozen=True)
class AccessContext:
    """O que o servidor MCP sabe de quem chama — só do token validado."""

    token_id: int
    grant_id: int
    user_id: int
    client_pk: int
    client_id: str
    client_name: str
    scopes: tuple[str, ...]
    expires_at: datetime
    resource: str


def create_grant(
    session: Session, *, user_id: int, client: OAuthClient, scopes: List[str], resource: str
) -> OAuthGrant:
    concessao = OAuthGrant(
        user_id=user_id,
        client_pk=client.id,
        client_name=client.client_name,
        scopes=escopos.to_string(scopes),
        resource=resource,
        last_used_at=_agora(),
    )
    session.add(concessao)
    session.flush()
    return concessao


def issue_for_grant(
    session: Session, grant: OAuthGrant, scopes: List[str], *, with_refresh: bool = True
) -> TokenPair:
    agora = _agora()
    ttl = timedelta(minutes=settings.MCP_ACCESS_TOKEN_TTL_MINUTES)
    access = crypto.new_secret(crypto.ACCESS_PREFIX)
    session.add(OAuthToken(
        grant_id=grant.id,
        kind="access",
        token_hash=crypto.sha256_hex(access),
        scopes=escopos.to_string(scopes),
        expires_at=agora + ttl,
    ))
    refresh = None
    if with_refresh:
        refresh = crypto.new_secret(crypto.REFRESH_PREFIX)
        session.add(OAuthToken(
            grant_id=grant.id,
            kind="refresh",
            token_hash=crypto.sha256_hex(refresh),
            scopes=escopos.to_string(scopes),
            expires_at=agora + timedelta(days=settings.MCP_REFRESH_TOKEN_TTL_DAYS),
        ))
    session.flush()
    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_in=int(ttl.total_seconds()),
        scope=escopos.to_string(scopes),
    )


def revoke_grant(session: Session, grant: OAuthGrant, reason: str) -> None:
    """Derruba a conexão e TODOS os tokens dela. Só flush (ADR 0010)."""
    agora = _agora()
    if grant.revoked_at is None:
        grant.revoked_at = agora
        grant.revoked_reason = reason
        session.add(grant)
    session.execute(
        update(OAuthToken)
        .where(OAuthToken.grant_id == grant.id, OAuthToken.revoked_at.is_(None))
        .values(revoked_at=agora)
    )
    session.flush()


def revoke_all_user_grants(session: Session, user_id: int, reason: str) -> int:
    """Troca/redefinição de senha, conta desativada, "revogar sessões" do admin:
    toda conexão de IA cai junto com as sessões do navegador."""
    concessoes = session.exec(
        select(OAuthGrant).where(OAuthGrant.user_id == user_id, OAuthGrant.revoked_at.is_(None))
    ).all()
    for concessao in concessoes:
        revoke_grant(session, concessao, reason)
    return len(concessoes)


def _usuario_ativo(session: Session, user_id: int) -> Optional[User]:
    user = session.get(User, user_id)
    if user is None or user.deleted_at is not None or not user.is_active:
        return None
    return user


def refresh(
    session: Session,
    *,
    client: OAuthClient,
    refresh_token: Optional[str],
    scope: Optional[str],
    resource: Optional[str],
) -> TokenPair:
    if "refresh_token" not in (client.grant_types or []):
        raise OAuthError("unauthorized_client", "este cliente não usa refresh_token")
    if not refresh_token or not refresh_token.startswith(crypto.REFRESH_PREFIX):
        raise OAuthError("invalid_grant", "refresh_token inválido")
    linha = session.exec(
        select(OAuthToken).where(
            OAuthToken.token_hash == crypto.sha256_hex(refresh_token),
            OAuthToken.kind == "refresh",
        )
    ).first()
    if linha is None:
        raise OAuthError("invalid_grant", "refresh_token inválido")
    concessao = session.get(OAuthGrant, linha.grant_id)
    if concessao is None or concessao.client_pk != client.id:
        raise OAuthError("invalid_grant", "refresh_token inválido")
    if concessao.revoked_at is not None or linha.revoked_at is not None:
        raise OAuthError("invalid_grant", "conexão revogada — reconecte o aplicativo")
    if linha.rotated_at is not None:
        revoke_grant(session, concessao, "refresh_reuse")
        raise OAuthError(
            "invalid_grant",
            "refresh_token reutilizado; por segurança a conexão foi revogada",
        )
    if _aware(linha.expires_at) <= _agora():
        raise OAuthError("invalid_grant", "refresh_token expirado — reconecte o aplicativo")
    if _usuario_ativo(session, concessao.user_id) is None:
        revoke_grant(session, concessao, "account_disabled")
        raise OAuthError("invalid_grant", "conta indisponível")
    if not same_resource(resource):
        raise OAuthError("invalid_target", "resource não corresponde a este servidor MCP")

    concedidos = escopos.split(linha.scopes)
    if scope:
        try:
            pedidos = escopos.parse(scope, default_all=False)
        except escopos.InvalidScope as exc:
            raise OAuthError("invalid_scope", str(exc))
        if not set(pedidos) <= set(concedidos):
            raise OAuthError("invalid_scope", "a renovação não pode ampliar os escopos concedidos")
        if not set(escopos.REQUIRED_SCOPES) <= set(pedidos):
            raise OAuthError("invalid_scope", f"o escopo {escopos.FINANCE_READ} é obrigatório")
    else:
        pedidos = concedidos

    agora = _agora()
    girou = session.execute(
        update(OAuthToken)
        .where(
            OAuthToken.id == linha.id,
            OAuthToken.rotated_at.is_(None),
            OAuthToken.revoked_at.is_(None),
        )
        .values(rotated_at=agora)
    )
    if girou.rowcount != 1:
        # Duas renovações com o MESMO refresh ao mesmo tempo: uma delas é cópia.
        revoke_grant(session, concessao, "refresh_reuse")
        raise OAuthError("invalid_grant", "refresh_token reutilizado; a conexão foi revogada")

    concessao.last_used_at = agora
    session.add(concessao)
    return issue_for_grant(session, concessao, pedidos)


def verify_access(session: Session, token: Optional[str]) -> Optional[AccessContext]:
    """Contexto do portador, ou `None` (o transporte responde 401)."""
    if not token or not token.startswith(crypto.ACCESS_PREFIX) or len(token) > 128:
        return None
    linha = session.exec(
        select(OAuthToken).where(
            OAuthToken.token_hash == crypto.sha256_hex(token),
            OAuthToken.kind == "access",
        )
    ).first()
    if linha is None or linha.revoked_at is not None:
        return None
    expira = _aware(linha.expires_at)
    if expira <= _agora():
        return None
    concessao = session.get(OAuthGrant, linha.grant_id)
    if concessao is None or concessao.revoked_at is not None:
        return None
    cliente = session.get(OAuthClient, concessao.client_pk)
    if cliente is None or cliente.disabled_at is not None:
        return None
    if _usuario_ativo(session, concessao.user_id) is None:
        return None
    return AccessContext(
        token_id=linha.id,
        grant_id=concessao.id,
        user_id=concessao.user_id,
        client_pk=cliente.id,
        client_id=cliente.client_id,
        client_name=concessao.client_name,
        scopes=tuple(escopos.split(linha.scopes)),
        expires_at=expira,
        resource=concessao.resource,
    )


def touch_grant(session: Session, grant_id: int, *, min_interval_seconds: int = 60) -> None:
    """Atualiza "último uso" da conexão, no máximo uma vez por minuto."""
    agora = _agora()
    limite = agora - timedelta(seconds=min_interval_seconds)
    session.execute(
        update(OAuthGrant)
        .where(
            OAuthGrant.id == grant_id,
            (OAuthGrant.last_used_at.is_(None)) | (OAuthGrant.last_used_at < limite),
        )
        .values(last_used_at=agora)
    )


def revoke_token(session: Session, *, client: OAuthClient, token: Optional[str]) -> None:
    """RFC 7009: revoga o token SE for deste cliente; nunca diz se existia.

    Revogar um refresh derruba a conexão inteira (os access dela também, §2.1);
    revogar um access derruba só ele.
    """
    if not token:
        return
    linha = session.exec(select(OAuthToken).where(OAuthToken.token_hash == crypto.sha256_hex(token))).first()
    if linha is None:
        return
    concessao = session.get(OAuthGrant, linha.grant_id)
    if concessao is None or concessao.client_pk != client.id:
        return
    if linha.kind == "refresh":
        revoke_grant(session, concessao, "client")
        return
    if linha.revoked_at is None:
        linha.revoked_at = _agora()
        session.add(linha)
        session.flush()
