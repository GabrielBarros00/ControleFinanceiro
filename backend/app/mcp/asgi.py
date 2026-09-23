"""O portão HTTP do `/mcp`: quem passa daqui tem identidade; quem não tem, recebe 401.

Por que um portão próprio e não o `RequireAuthMiddleware` do SDK:

- o desafio 401 precisa carregar `scope=` além do `resource_metadata` (a spec
  recomenda, e é o que o Claude usa para escolher os escopos a pedir);
- a validação do token é uma consulta ao banco (a revogação vale na próxima
  chamada), e roda em threadpool para não travar o event loop;
- a identidade resolvida vira o `McpIdentity` que as tools leem.

**Origin (DNS rebinding).** A spec exige validar `Origin` em toda conexão:
presente e fora da lista → 403. Servidor-a-servidor (ChatGPT, Claude) não manda
`Origin`; navegador manda. A lista é a origem do próprio site mais
`MCP_ALLOWED_ORIGINS`. O `Host` já foi validado pelo `TrustedHostMiddleware` do
app, então a checagem de host do SDK fica desligada (seria a mesma regra, com
uma sintaxe de curinga diferente).

**Montagem por lifespan.** O gerenciador de sessões do SDK só roda UMA vez por
instância; o app HTTP do MCP é recriado a cada lifespan — o que permite à suíte
subir o app várias vezes no mesmo processo.
"""
from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import AsyncIterator, Optional

from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.transport_security import TransportSecuritySettings
from starlette.authentication import AuthCredentials
from starlette.concurrency import run_in_threadpool
from starlette.types import Receive, Scope, Send

from app.core.config import settings
from app.db import session as db_session
from app.mcp.identity import McpIdentity, reset_identity, set_identity
from app.services.oauth import scopes as escopos, tokens

_state = SimpleNamespace(app=None)
MAX_CORPO = 1024 * 1024


def _cabecalho(scope: Scope, nome: bytes) -> Optional[str]:
    for chave, valor in scope.get("headers", []):
        if chave == nome:
            return valor.decode("latin-1")
    return None


def allowed_origins() -> set[str]:
    return {settings.oauth_issuer.rstrip("/"), *settings.mcp_allowed_origins_list}


async def _json(send: Send, status: int, corpo: dict, headers: Optional[list] = None) -> None:
    dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(dados)).encode()),
            (b"cache-control", b"no-store"),
            *(headers or []),
        ],
    })
    await send({"type": "http.response.body", "body": dados})


def challenge(*, token_presented: bool) -> str:
    partes = []
    if token_presented:
        partes.append('error="invalid_token"')
        # Cabeçalho HTTP é ASCII: descrição sem acento, de propósito.
        partes.append('error_description="The access token is invalid, expired or revoked"')
    partes.append(f'resource_metadata="{settings.oauth_issuer}/.well-known/oauth-protected-resource/mcp"')
    partes.append(f'scope="{" ".join(escopos.ALL_SCOPES)}"')
    return "Bearer " + ", ".join(partes)


def _verifica(token: str) -> Optional[tokens.AccessContext]:
    with db_session.session_scope() as sessao:
        contexto = tokens.verify_access(sessao, token)
        if contexto is not None:
            tokens.touch_grant(sessao, contexto.grant_id)
            sessao.commit()
        return contexto


class McpGate:
    """Endpoint ASGI do `/mcp` (classe: o Starlette só trata `Route` como ASGI
    puro quando o endpoint não é função)."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not settings.MCP_ENABLED:
            await _json(send, 404, {"error": {"code": "NOT_FOUND", "message": "Não encontrado", "details": {}}})
            return

        # `/mcp/` e `/mcp` são o mesmo endpoint — sem 307 (o salto perde o
        # Authorization em alguns clientes, como perdia o cookie no app).
        scope = {**scope, "path": "/mcp", "raw_path": b"/mcp"}

        # Corpo de tool call é pequeno (a maior entrada é uma importação de 200
        # linhas). O nginx já corta em 1 MB; aqui vale também sem proxy na frente.
        tamanho = _cabecalho(scope, b"content-length")
        if tamanho and tamanho.isdigit() and int(tamanho) > MAX_CORPO:
            await _json(send, 413, {"jsonrpc": "2.0", "error": {"code": -32600, "message": "Corpo grande demais"}})
            return

        origem = _cabecalho(scope, b"origin")
        if origem and origem.rstrip("/") not in allowed_origins():
            await _json(send, 403, {
                "jsonrpc": "2.0",
                "error": {"code": -32000, "message": "Origin não permitida"},
            })
            return

        autorizacao = _cabecalho(scope, b"authorization") or ""
        token = autorizacao[7:].strip() if autorizacao.lower().startswith("bearer ") else None
        contexto = await run_in_threadpool(_verifica, token) if token else None
        if contexto is None:
            await _json(
                send, 401,
                {"error": "invalid_token", "error_description": "Autenticação necessária"},
                headers=[(b"www-authenticate", challenge(token_presented=bool(token)).encode("utf-8"))],
            )
            return

        app = _state.app
        if app is None:
            await _json(send, 503, {"error": {"code": "UNAVAILABLE", "message": "Servidor MCP iniciando", "details": {}}})
            return

        identidade = McpIdentity(
            user_id=contexto.user_id,
            grant_id=contexto.grant_id,
            client_pk=contexto.client_pk,
            client_id=contexto.client_id,
            client_name=contexto.client_name,
            scopes=frozenset(contexto.scopes),
            # Gerado AQUI, nunca lido do cliente: é o `correlation_id` que o erro
            # mostra ao agente e que se procura no log — um valor escolhido por
            # quem chama poderia colidir de propósito com o de outra pessoa.
            request_id=uuid.uuid4().hex[:16],
            client_info=(_cabecalho(scope, b"user-agent") or None),
        )
        acesso = AccessToken(
            token="[redacted]",
            client_id=contexto.client_id,
            scopes=list(contexto.scopes),
            expires_at=int(contexto.expires_at.timestamp()),
            resource=contexto.resource,
            subject=str(contexto.user_id),
        )
        usuario = AuthenticatedUser(acesso)
        scope["user"] = usuario
        scope["auth"] = AuthCredentials(list(contexto.scopes))
        marca_identidade = set_identity(identidade)
        marca_sdk = auth_context_var.set(usuario)
        try:
            await app(scope, receive, send)
        finally:
            auth_context_var.reset(marca_sdk)
            reset_identity(marca_identidade)


@asynccontextmanager
async def lifespan() -> AsyncIterator[None]:
    if not settings.MCP_ENABLED:
        yield
        return
    from app.mcp.server import get_server

    servidor = get_server()
    _state.app = servidor.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    try:
        async with servidor.session_manager.run():
            yield
    finally:
        _state.app = None
