"""Clientes OAuth: registro dinâmico (DCR, RFC 7591) e CIMD.

**Tudo que vem do cliente é dado não confiável.** Nome, `client_uri` e o próprio
`client_id` CIMD são escolhidos por quem inicia o fluxo — qualquer pessoa. Por
isso a tela de consentimento mostra o HOST do redirect (é para lá que o código
vai) e o nome aparece como "informado pelo aplicativo".

**Regra dos redirects** (spec MCP 2026-07-28, OAuth 2.1 §7.12):
- só `https`, ou `http` para loopback (`localhost`, `127.0.0.1`, `[::1]`);
- sem fragmento, sem credenciais, sem curinga;
- comparação EXATA com o registrado, com uma exceção: loopback compara sem a
  porta (RFC 8252 §7.3). É o que o Claude Code declara no CIMD dele
  (`http://localhost/callback`) e usa numa porta efêmera diferente a cada login.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, UTC
from typing import Any, Optional, Tuple
from urllib.parse import urlsplit

from sqlmodel import Session, select

from app.core.config import settings
from app.models.oauth import OAuthClient
from app.services.oauth import cimd_fetch, crypto
from app.services.oauth.errors import OAuthError

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})
MAX_REDIRECT_URIS = 10
AUTH_METHODS = ("none", "client_secret_basic", "client_secret_post")
GRANT_TYPES = ("authorization_code", "refresh_token")
_CONTROLE = re.compile(r"[\x00-\x1f\x7f]")


def _agora() -> datetime:
    return datetime.now(UTC)


def _aware(momento: Optional[datetime]) -> Optional[datetime]:
    if momento is None:
        return None
    return momento if momento.tzinfo else momento.replace(tzinfo=UTC)


def clean_text(value: Any, limit: int) -> Optional[str]:
    """Texto do cliente para exibição: sem caracteres de controle, aparado."""
    if not isinstance(value, str):
        return None
    texto = _CONTROLE.sub("", value).strip()
    return texto[:limit] or None


def is_loopback(uri: str) -> bool:
    try:
        partes = urlsplit(uri)
    except ValueError:
        return False
    return partes.scheme == "http" and (partes.hostname or "").lower() in LOOPBACK_HOSTS


def validate_redirect_uri(uri: Any) -> str:
    if not isinstance(uri, str) or not uri or len(uri) > 2048:
        raise OAuthError("invalid_redirect_uri", "redirect_uri inválido")
    try:
        partes = urlsplit(uri)
        partes.port  # noqa: B018 — força a validação da porta
    except ValueError:
        raise OAuthError("invalid_redirect_uri", "redirect_uri inválido")
    if partes.fragment or partes.username or partes.password or not partes.hostname:
        raise OAuthError("invalid_redirect_uri", "redirect_uri não pode ter fragmento nem credenciais")
    if "*" in uri:
        raise OAuthError("invalid_redirect_uri", "redirect_uri não pode ter curinga")
    if partes.scheme == "https":
        return uri
    if partes.scheme == "http" and (partes.hostname or "").lower() in LOOPBACK_HOSTS:
        return uri
    raise OAuthError(
        "invalid_redirect_uri",
        "redirect_uri precisa usar https (ou http em localhost/127.0.0.1)",
    )


def redirect_uri_matches(registered: list[str], presented: str) -> bool:
    """O redirect apresentado bate com um dos registrados?"""
    if presented in registered:
        return True
    if not is_loopback(presented):
        return False
    alvo = urlsplit(presented)
    for uri in registered:
        if not is_loopback(uri):
            continue
        base = urlsplit(uri)
        if (
            (base.hostname or "").lower() == (alvo.hostname or "").lower()
            and base.path == alvo.path
            and base.query == alvo.query
        ):
            return True
    return False


def _valida_lista_de_redirects(valor: Any) -> list[str]:
    if not isinstance(valor, list) or not valor:
        raise OAuthError("invalid_redirect_uri", "redirect_uris é obrigatório")
    if len(valor) > MAX_REDIRECT_URIS:
        raise OAuthError("invalid_redirect_uri", f"no máximo {MAX_REDIRECT_URIS} redirect_uris")
    return [validate_redirect_uri(uri) for uri in valor]


def _valida_client_uri(valor: Any) -> Optional[str]:
    if not isinstance(valor, str) or not valor:
        return None
    try:
        partes = urlsplit(valor)
    except ValueError:
        return None
    if partes.scheme != "https" or not partes.hostname or len(valor) > 512:
        return None
    return valor


# --- DCR (RFC 7591) ------------------------------------------------------------

def register_dcr(session: Session, metadata: Any) -> Tuple[OAuthClient, Optional[str]]:
    """Registra um cliente. Devolve `(cliente, segredo_em_claro_ou_None)`."""
    if not settings.MCP_DCR_ENABLED:
        raise OAuthError("invalid_client_metadata", "registro dinâmico desativado neste servidor")
    if not isinstance(metadata, dict):
        raise OAuthError("invalid_client_metadata", "o corpo deve ser um objeto JSON")

    redirects = _valida_lista_de_redirects(metadata.get("redirect_uris"))

    # RFC 7591 §2: sem `token_endpoint_auth_method` o padrão é client_secret_basic.
    metodo = metadata.get("token_endpoint_auth_method") or "client_secret_basic"
    if metodo not in AUTH_METHODS:
        raise OAuthError(
            "invalid_client_metadata",
            f"token_endpoint_auth_method não suportado: use {', '.join(AUTH_METHODS)}",
        )

    grants = metadata.get("grant_types") or ["authorization_code"]
    if not isinstance(grants, list) or not grants or any(g not in GRANT_TYPES for g in grants):
        raise OAuthError("invalid_client_metadata", "grant_types aceitos: authorization_code, refresh_token")
    if "authorization_code" not in grants:
        raise OAuthError("invalid_client_metadata", "authorization_code é obrigatório em grant_types")

    responses = metadata.get("response_types") or ["code"]
    if responses != ["code"]:
        raise OAuthError("invalid_client_metadata", "response_types aceito: code")

    tipo = metadata.get("application_type")
    if tipo is not None and tipo not in ("native", "web"):
        raise OAuthError("invalid_client_metadata", "application_type aceito: native ou web")

    segredo = None
    segredo_hash = None
    if metodo != "none":
        segredo = crypto.new_secret(crypto.CLIENT_SECRET_PREFIX)
        segredo_hash = crypto.sha256_hex(segredo)

    cliente = OAuthClient(
        client_id=f"cfm_dcr_{secrets.token_urlsafe(18)}",
        kind="dcr",
        client_name=clean_text(metadata.get("client_name"), 120) or "Cliente MCP",
        client_uri=_valida_client_uri(metadata.get("client_uri")),
        redirect_uris=redirects,
        grant_types=list(dict.fromkeys(grants)),
        token_endpoint_auth_method=metodo,
        client_secret_hash=segredo_hash,
        application_type=tipo,
        software_id=clean_text(metadata.get("software_id"), 120),
        software_version=clean_text(metadata.get("software_version"), 60),
    )
    session.add(cliente)
    session.flush()
    return cliente, segredo


def registration_response(cliente: OAuthClient, segredo: Optional[str]) -> dict:
    corpo: dict[str, Any] = {
        "client_id": cliente.client_id,
        "client_id_issued_at": int(_aware(cliente.created_at).timestamp()),
        "client_name": cliente.client_name,
        "redirect_uris": cliente.redirect_uris,
        "grant_types": cliente.grant_types,
        "response_types": ["code"],
        "token_endpoint_auth_method": cliente.token_endpoint_auth_method,
    }
    if cliente.client_uri:
        corpo["client_uri"] = cliente.client_uri
    if cliente.application_type:
        corpo["application_type"] = cliente.application_type
    if segredo:
        corpo["client_secret"] = segredo
        corpo["client_secret_expires_at"] = 0
    return corpo


# --- CIMD ------------------------------------------------------------------------

def _metodo_do_cimd(documento: dict) -> str:
    """Método de autenticação que ESTE servidor vai usar com o cliente CIMD.

    Cliente CIMD aqui é sempre público (`none`, só PKCE). O ChatGPT publica
    `token_endpoint_auth_methods_supported: ["none", "private_key_jwt"]` e escolhe
    pela interseção com os nossos metadados — sem `private_key_jwt` do nosso lado,
    fica `none`. Um documento que SÓ aceita `private_key_jwt` não é atendível.
    """
    suportados = documento.get("token_endpoint_auth_methods_supported")
    preferido = documento.get("token_endpoint_auth_method")
    if isinstance(suportados, list) and "none" in suportados:
        return "none"
    if preferido in (None, "none"):
        return "none"
    raise OAuthError(
        "invalid_client",
        "o documento do cliente exige um método de autenticação que este servidor não oferece",
    )


def resolve_cimd_client(session: Session, client_id: str, *, force: bool = False) -> OAuthClient:
    """Cliente CIMD do cache ou da rede (respeitando a validade do documento)."""
    if not settings.MCP_CIMD_ENABLED:
        raise OAuthError("invalid_client", "clientes por URL (CIMD) estão desativados neste servidor")
    existente = session.exec(select(OAuthClient).where(OAuthClient.client_id == client_id)).first()
    if existente is not None and existente.disabled_at is not None:
        raise OAuthError("invalid_client", "cliente desativado")
    if (
        existente is not None
        and not force
        and existente.metadata_expires_at is not None
        and _aware(existente.metadata_expires_at) > _agora()
    ):
        return existente

    try:
        documento, ttl = cimd_fetch.fetch_client_metadata(client_id)
    except cimd_fetch.CimdFetchError as exc:
        raise OAuthError("invalid_client", f"não foi possível validar o cliente: {exc}")

    if documento.get("client_id") != client_id:
        raise OAuthError("invalid_client", "o documento do cliente não corresponde ao client_id")
    nome = clean_text(documento.get("client_name"), 120)
    if not nome:
        raise OAuthError("invalid_client", "o documento do cliente não informa client_name")
    try:
        redirects = _valida_lista_de_redirects(documento.get("redirect_uris"))
    except OAuthError as exc:
        raise OAuthError("invalid_client", f"documento do cliente: {exc.description}")
    metodo = _metodo_do_cimd(documento)
    grants = documento.get("grant_types") or ["authorization_code"]
    if not isinstance(grants, list):
        grants = ["authorization_code"]
    grants = [g for g in grants if g in GRANT_TYPES] or ["authorization_code"]

    cliente = existente or OAuthClient(client_id=client_id, kind="cimd", client_name=nome)
    cliente.client_name = nome
    cliente.client_uri = _valida_client_uri(documento.get("client_uri"))
    cliente.redirect_uris = redirects
    cliente.grant_types = grants
    cliente.token_endpoint_auth_method = metodo
    cliente.application_type = documento.get("application_type") if documento.get("application_type") in ("native", "web") else None
    cliente.metadata_expires_at = _agora() + timedelta(seconds=ttl)
    cliente.updated_at = _agora()
    session.add(cliente)
    session.flush()
    return cliente


# --- Busca e autenticação ----------------------------------------------------------

def get_client(session: Session, client_id: Optional[str], *, refresh_cimd: bool = False) -> OAuthClient:
    """Cliente pelo `client_id`, ou `invalid_client`.

    `refresh_cimd=True` (no /authorize) re-busca o documento vencido; no /token o
    registro do /authorize basta — o redirect já foi validado contra ele.
    """
    if not client_id or len(client_id) > 512:
        raise OAuthError("invalid_client", "client_id ausente ou inválido", 401)
    if client_id.startswith("https://"):
        if refresh_cimd:
            return resolve_cimd_client(session, client_id)
        cliente = session.exec(select(OAuthClient).where(OAuthClient.client_id == client_id)).first()
        if cliente is None:
            return resolve_cimd_client(session, client_id)
    else:
        cliente = session.exec(select(OAuthClient).where(OAuthClient.client_id == client_id)).first()
    if cliente is None or cliente.disabled_at is not None:
        raise OAuthError("invalid_client", "cliente desconhecido", 401)
    return cliente


def authenticate_client(
    session: Session,
    *,
    client_id: Optional[str],
    client_secret: Optional[str],
    via_basic: bool,
) -> OAuthClient:
    """Autenticação no /token e no /revoke (RFC 6749 §2.3)."""
    cliente = get_client(session, client_id)
    metodo = cliente.token_endpoint_auth_method
    if metodo == "none":
        if client_secret:
            # Cliente público mandando segredo: não há o que conferir, e aceitar
            # daria a impressão de que o segredo vale alguma coisa.
            raise OAuthError("invalid_client", "este cliente é público e não usa segredo", 401)
        return cliente
    if not client_secret or not cliente.client_secret_hash:
        raise OAuthError("invalid_client", "autenticação do cliente obrigatória", 401)
    if metodo == "client_secret_basic" and not via_basic:
        raise OAuthError("invalid_client", "use HTTP Basic para autenticar este cliente", 401)
    if metodo == "client_secret_post" and via_basic:
        raise OAuthError("invalid_client", "envie client_secret no corpo para este cliente", 401)
    if not crypto.same(crypto.sha256_hex(client_secret), cliente.client_secret_hash):
        raise OAuthError("invalid_client", "credenciais do cliente inválidas", 401)
    return cliente
