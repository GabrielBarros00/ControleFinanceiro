"""O pedido de autorização: validar, consentir, emitir e trocar o código.

**Duas classes de erro no `/authorize`** (RFC 6749 §4.1.2.1), e confundi-las é o
defeito clássico:

- `FatalAuthorizeError` — `client_id` ou `redirect_uri` inválidos. NÃO se
  redireciona: o redirect ainda não foi validado, e redirecionar para ele faria
  deste servidor um *open redirector*. A pessoa vê a página de erro do app.
- `RedirectableError` — o resto (escopo, PKCE, `response_type`, `resource`).
  Volta para o redirect JÁ VALIDADO com `error`, `state` e `iss`.

**O pedido validado viaja assinado**, como os demais tokens de propósito do app
(`create_purpose_token`): a tela de consentimento recebe um handle opaco, e o que
ela aprova é exatamente o que foi validado — ninguém troca o redirect no meio.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, UTC
from typing import Mapping, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import update
from sqlmodel import Session, select

from app.core.config import settings
from app.core.jwt import create_purpose_token, decode_token
from app.models.oauth import OAuthAuthorizationCode, OAuthClient, OAuthGrant
from app.models.user import User
from app.services.oauth import clients, crypto, scopes as escopos, tokens
from app.services.oauth.errors import OAuthError

REQUEST_PURPOSE = "oauth_authz_request"
REQUEST_TTL = timedelta(minutes=10)
MAX_STATE = 1024


class FatalAuthorizeError(Exception):
    """Erro que NÃO pode voltar para o redirect (cliente/redirect inválidos)."""

    def __init__(self, error: str, description: str):
        super().__init__(description)
        self.error = error
        self.description = description


class RedirectableError(Exception):
    def __init__(self, error: str, description: str, redirect_uri: str, state: Optional[str]):
        super().__init__(description)
        self.error = error
        self.description = description
        self.redirect_uri = redirect_uri
        self.state = state

    def location(self) -> str:
        return build_redirect(self.redirect_uri, {
            "error": self.error,
            "error_description": self.description,
            "state": self.state,
        })


@dataclass(frozen=True)
class AuthorizationRequest:
    client_id: str
    redirect_uri: str
    scopes: tuple[str, ...]
    state: Optional[str]
    code_challenge: str
    resource: str


def _agora() -> datetime:
    return datetime.now(UTC)


def _aware(momento: datetime) -> datetime:
    return momento if momento.tzinfo else momento.replace(tzinfo=UTC)


def build_redirect(redirect_uri: str, params: Mapping[str, Optional[str]]) -> str:
    """Acrescenta os parâmetros ao redirect preservando a query que ele já tem,
    sempre com `iss` (RFC 9207 — o cliente confere o emissor antes de trocar o
    código, o que fecha o ataque de mix-up)."""
    partes = urlsplit(redirect_uri)
    atuais = parse_qsl(partes.query, keep_blank_values=True)
    novos = [(k, v) for k, v in params.items() if v is not None]
    novos.append(("iss", settings.oauth_issuer))
    query = urlencode(atuais + novos)
    return urlunsplit((partes.scheme, partes.netloc, partes.path, query, ""))


def validate_authorize(session: Session, params: Mapping[str, str]) -> Tuple[OAuthClient, AuthorizationRequest]:
    try:
        cliente = clients.get_client(session, params.get("client_id"), refresh_cimd=True)
    except OAuthError as exc:
        raise FatalAuthorizeError(exc.error, exc.description)

    redirect = params.get("redirect_uri")
    if not redirect:
        if len(cliente.redirect_uris) == 1 and not clients.is_loopback(cliente.redirect_uris[0]):
            redirect = cliente.redirect_uris[0]
        else:
            raise FatalAuthorizeError("invalid_request", "redirect_uri é obrigatório para este cliente")
    try:
        clients.validate_redirect_uri(redirect)
    except OAuthError as exc:
        raise FatalAuthorizeError("invalid_request", exc.description)
    if not clients.redirect_uri_matches(cliente.redirect_uris, redirect):
        raise FatalAuthorizeError("invalid_request", "redirect_uri não registrado para este cliente")

    state = params.get("state")
    if state is not None and len(state) > MAX_STATE:
        raise FatalAuthorizeError("invalid_request", "state longo demais")

    def erro(codigo: str, descricao: str) -> RedirectableError:
        return RedirectableError(codigo, descricao, redirect, state)

    if params.get("response_type") != "code":
        raise erro("unsupported_response_type", "response_type deve ser code")
    if "authorization_code" not in (cliente.grant_types or []):
        raise erro("unauthorized_client", "cliente não registrado para authorization_code")
    desafio = params.get("code_challenge")
    if not crypto.valid_pkce_value(desafio):
        raise erro("invalid_request", "code_challenge (PKCE) é obrigatório")
    if params.get("code_challenge_method") != "S256":
        raise erro("invalid_request", "code_challenge_method deve ser S256")
    try:
        pedidos = escopos.parse(params.get("scope"))
    except escopos.InvalidScope as exc:
        raise erro("invalid_scope", str(exc))
    pedidos = escopos.canonical(list(pedidos) + list(escopos.REQUIRED_SCOPES))
    recurso = params.get("resource")
    if not tokens.same_resource(recurso):
        raise erro("invalid_target", "resource não corresponde a este servidor MCP")

    return cliente, AuthorizationRequest(
        client_id=cliente.client_id,
        redirect_uri=redirect,
        scopes=tuple(pedidos),
        state=state,
        code_challenge=desafio,
        resource=settings.mcp_resource_url,
    )


def issue_request_handle(pedido: AuthorizationRequest) -> str:
    return create_purpose_token(
        {
            "cid": pedido.client_id,
            "ru": pedido.redirect_uri,
            "sc": " ".join(pedido.scopes),
            "st": pedido.state,
            "cc": pedido.code_challenge,
            "rs": pedido.resource,
        },
        purpose=REQUEST_PURPOSE,
        expires_delta=REQUEST_TTL,
    )


def read_request_handle(handle: Optional[str]) -> AuthorizationRequest:
    if not handle or len(handle) > 8192:
        raise OAuthError("invalid_request", "pedido de autorização ausente")
    try:
        dados = decode_token(handle)
    except Exception:
        raise OAuthError("invalid_request", "pedido de autorização inválido ou expirado")
    if dados.get("token_type") != REQUEST_PURPOSE:
        raise OAuthError("invalid_request", "pedido de autorização inválido")
    return AuthorizationRequest(
        client_id=dados["cid"],
        redirect_uri=dados["ru"],
        scopes=tuple(escopos.split(dados.get("sc") or "")),
        state=dados.get("st"),
        code_challenge=dados["cc"],
        resource=dados["rs"],
    )


def approve(
    session: Session,
    *,
    pedido: AuthorizationRequest,
    user: User,
    approved_scopes: list[str],
) -> str:
    cliente = clients.get_client(session, pedido.client_id)
    aprovados = escopos.canonical(approved_scopes)
    if not set(aprovados) <= set(pedido.scopes):
        raise OAuthError("invalid_scope", "escopo aprovado fora do que o aplicativo pediu")
    if not set(escopos.REQUIRED_SCOPES) <= set(aprovados):
        raise OAuthError("invalid_scope", f"o escopo {escopos.FINANCE_READ} é obrigatório")

    codigo = crypto.new_secret(crypto.CODE_PREFIX)
    session.add(OAuthAuthorizationCode(
        code_hash=crypto.sha256_hex(codigo),
        client_pk=cliente.id,
        user_id=user.id,
        redirect_uri=pedido.redirect_uri,
        scopes=escopos.to_string(aprovados),
        resource=pedido.resource,
        code_challenge=pedido.code_challenge,
        expires_at=_agora() + timedelta(seconds=settings.MCP_AUTH_CODE_TTL_SECONDS),
    ))
    cliente.last_used_at = _agora()
    session.add(cliente)
    session.flush()
    return build_redirect(pedido.redirect_uri, {"code": codigo, "state": pedido.state})


def deny(pedido: AuthorizationRequest) -> str:
    return build_redirect(pedido.redirect_uri, {
        "error": "access_denied",
        "error_description": "A pessoa recusou o acesso.",
        "state": pedido.state,
    })


def exchange_code(
    session: Session,
    *,
    client: OAuthClient,
    code: Optional[str],
    redirect_uri: Optional[str],
    code_verifier: Optional[str],
    resource: Optional[str],
) -> tokens.TokenPair:
    if not code or not code.startswith(crypto.CODE_PREFIX):
        raise OAuthError("invalid_grant", "código de autorização inválido")
    linha = session.exec(
        select(OAuthAuthorizationCode).where(OAuthAuthorizationCode.code_hash == crypto.sha256_hex(code))
    ).first()
    if linha is None or linha.client_pk != client.id:
        raise OAuthError("invalid_grant", "código de autorização inválido")

    usado = session.execute(
        update(OAuthAuthorizationCode)
        .where(OAuthAuthorizationCode.id == linha.id, OAuthAuthorizationCode.used_at.is_(None))
        .values(used_at=_agora())
    )
    if usado.rowcount != 1:
        # Código reapresentado: quem o reusa pode ser quem o interceptou. A
        # conexão emitida com ele cai (OAuth 2.1 §4.1.3).
        if linha.grant_id is not None:
            concessao = session.get(OAuthGrant, linha.grant_id)
            if concessao is not None:
                tokens.revoke_grant(session, concessao, "code_reuse")
        raise OAuthError("invalid_grant", "código de autorização já utilizado")

    if _aware(linha.expires_at) <= _agora():
        raise OAuthError("invalid_grant", "código de autorização expirado")
    if redirect_uri is not None and redirect_uri != linha.redirect_uri:
        raise OAuthError("invalid_grant", "redirect_uri diferente do usado na autorização")
    if not code_verifier or not crypto.verify_pkce(code_verifier, linha.code_challenge):
        raise OAuthError("invalid_grant", "code_verifier (PKCE) não confere")
    if not tokens.same_resource(resource):
        raise OAuthError("invalid_target", "resource não corresponde a este servidor MCP")
    user = session.get(User, linha.user_id)
    if user is None or user.deleted_at is not None or not user.is_active:
        raise OAuthError("invalid_grant", "conta indisponível")

    concedidos = escopos.split(linha.scopes)
    concessao = tokens.create_grant(
        session, user_id=user.id, client=client, scopes=concedidos, resource=linha.resource
    )
    linha.grant_id = concessao.id
    session.add(linha)
    com_refresh = "refresh_token" in (client.grant_types or [])
    return tokens.issue_for_grant(session, concessao, concedidos, with_refresh=com_refresh)
