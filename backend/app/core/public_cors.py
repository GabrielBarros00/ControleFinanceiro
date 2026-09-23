"""CORS dos endpoints PÚBLICOS da integração MCP (ADR 0035).

O CORS global do app (`CORSMiddleware` com credenciais) só atende as origens do
próprio SPA — e está certo que seja assim para toda rota que lê cookie. Os
endpoints daqui são outra coisa: não usam cookie nenhum (a autenticação é PKCE,
segredo de cliente ou bearer), e ferramentas que rodam no navegador — o MCP
Inspector, por exemplo — precisam descobrir os metadados e trocar o código a
partir de outra origem.

- Metadados e endpoints OAuth sem sessão (`/.well-known/oauth-*`, `/token`,
  `/register`, `/revoke`): `Access-Control-Allow-Origin: *`, SEM credenciais. O
  asterisco sem credenciais é seguro justamente porque o navegador não anexa
  cookie nenhum.
- `/mcp`: só as origens de `MCP_ALLOWED_ORIGINS` (vazio por padrão). Origem
  estranha no `/mcp` é recusada com 403 pela proteção de DNS rebinding do
  transporte, e aqui não recebe cabeçalho CORS.

Middleware ASGI puro (não `BaseHTTPMiddleware`): não bufferiza o corpo e roda
por fora do CORS global, atendendo o preflight antes que ele o recuse.
"""
from typing import Iterable

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings

_PUBLICOS_EXATOS = frozenset({
    "/.well-known/oauth-authorization-server",
    "/.well-known/oauth-protected-resource",
    "/.well-known/oauth-protected-resource/mcp",
    "/api/v1/oauth/token",
    "/api/v1/oauth/register",
    "/api/v1/oauth/revoke",
})

_MCP = frozenset({"/mcp", "/mcp/"})

_CABECALHOS_OAUTH = "Authorization, Content-Type, MCP-Protocol-Version"
_CABECALHOS_MCP = (
    "Authorization, Content-Type, Accept, MCP-Protocol-Version, Mcp-Method, Mcp-Name, "
    "Mcp-Session-Id, Last-Event-ID"
)


def is_public_oauth_path(path: str) -> bool:
    return path in _PUBLICOS_EXATOS


def _cabecalho(scope: Scope, nome: bytes) -> str | None:
    for chave, valor in scope.get("headers", []):
        if chave == nome:
            return valor.decode("latin-1")
    return None


def _sem(headers: Iterable[tuple[bytes, bytes]], nomes: set[bytes]) -> list[tuple[bytes, bytes]]:
    return [(k, v) for k, v in headers if k.lower() not in nomes]


class PublicCorsMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        caminho = scope.get("path", "")
        origem = _cabecalho(scope, b"origin")

        if is_public_oauth_path(caminho):
            permitir = b"*"
            metodos = b"GET, POST, OPTIONS"
            cabecalhos = _CABECALHOS_OAUTH.encode()
            expor = b""
        elif caminho in _MCP and origem and origem.rstrip("/") in settings.mcp_allowed_origins_list:
            permitir = origem.encode("latin-1")
            metodos = b"GET, POST, DELETE, OPTIONS"
            cabecalhos = _CABECALHOS_MCP.encode()
            expor = b"Mcp-Session-Id, WWW-Authenticate"
        else:
            await self.app(scope, receive, send)
            return

        if scope["method"] == "OPTIONS" and _cabecalho(scope, b"access-control-request-method"):
            resposta = [
                (b"access-control-allow-origin", permitir),
                (b"access-control-allow-methods", metodos),
                (b"access-control-allow-headers", cabecalhos),
                (b"access-control-max-age", b"600"),
                (b"vary", b"Origin"),
                (b"content-length", b"0"),
            ]
            await send({"type": "http.response.start", "status": 204, "headers": resposta})
            await send({"type": "http.response.body", "body": b""})
            return

        async def enviar(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = _sem(
                    message.get("headers", []),
                    {b"access-control-allow-origin", b"access-control-allow-credentials"},
                )
                headers.append((b"access-control-allow-origin", permitir))
                if expor:
                    headers.append((b"access-control-expose-headers", expor))
                headers.append((b"vary", b"Origin"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, enviar)
