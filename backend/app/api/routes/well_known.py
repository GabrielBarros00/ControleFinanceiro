"""Documentos de descoberta em `/.well-known/*` (ADR 0035).

Moram na RAIZ do site, fora de `/api/v1`, porque é lá que os clientes procuram:

- `oauth-protected-resource[/mcp]` (RFC 9728) — "quem autoriza este servidor
  MCP". O `/mcp` no fim é a inserção de caminho da spec; a variante sem caminho é
  o segundo lugar que o cliente tenta.
- `oauth-authorization-server` (RFC 8414) — os endpoints e capacidades do AS.
  `client_id_metadata_document_supported` + `none` em
  `token_endpoint_auth_methods_supported` são as DUAS condições para o Claude
  escolher CIMD; `authorization_response_iss_parameter_supported` é o que faz o
  ChatGPT usar o redirect estável.
- `openai-apps-challenge` — verificação de domínio da OpenAI na submissão do app.

Nada aqui é sigiloso, e por isso tudo responde com CORS aberto (ver
`core/public_cors.py`): o MCP Inspector faz a descoberta no navegador.
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

from app.core.config import settings
from app.services.oauth import clients, scopes as escopos

router = APIRouter(prefix="/.well-known", include_in_schema=False)


def _habilitado() -> None:
    if not settings.MCP_ENABLED:
        raise HTTPException(status_code=404, detail="Não encontrado")


def protected_resource_metadata() -> dict:
    return {
        "resource": settings.mcp_resource_url,
        "authorization_servers": [settings.oauth_issuer],
        "scopes_supported": list(escopos.ALL_SCOPES),
        "bearer_methods_supported": ["header"],
        "resource_name": "Controle Financeiro",
        "resource_documentation": f"{settings.oauth_issuer}/me/settings?aba=integracoes",
    }


def authorization_server_metadata() -> dict:
    base = f"{settings.oauth_issuer}/api/v1/oauth"
    corpo = {
        "issuer": settings.oauth_issuer,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/token",
        "revocation_endpoint": f"{base}/revoke",
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": list(clients.AUTH_METHODS),
        "revocation_endpoint_auth_methods_supported": list(clients.AUTH_METHODS),
        "scopes_supported": list(escopos.ALL_SCOPES),
        "authorization_response_iss_parameter_supported": True,
        "client_id_metadata_document_supported": settings.MCP_CIMD_ENABLED,
        "service_documentation": f"{settings.oauth_issuer}/me/settings?aba=integracoes",
        "ui_locales_supported": ["pt-BR"],
    }
    if settings.MCP_DCR_ENABLED:
        corpo["registration_endpoint"] = f"{base}/register"
    return corpo


@router.get("/oauth-protected-resource")
@router.get("/oauth-protected-resource/mcp")
def oauth_protected_resource():
    _habilitado()
    return JSONResponse(protected_resource_metadata(), headers={"Cache-Control": "public, max-age=300"})


@router.get("/oauth-authorization-server")
def oauth_authorization_server():
    _habilitado()
    return JSONResponse(authorization_server_metadata(), headers={"Cache-Control": "public, max-age=300"})


@router.get("/openai-apps-challenge")
def openai_apps_challenge():
    """Só o token, em texto puro — é o que a verificação da OpenAI lê."""
    if not settings.MCP_ENABLED or not settings.OPENAI_APPS_CHALLENGE_TOKEN:
        raise HTTPException(status_code=404, detail="Não encontrado")
    return PlainTextResponse(settings.OPENAI_APPS_CHALLENGE_TOKEN.strip())
