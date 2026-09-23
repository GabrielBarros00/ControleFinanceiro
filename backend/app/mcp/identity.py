"""Quem está chamando — definido pelo portão HTTP a partir do token, e SÓ dele.

Nenhuma tool recebe `user_id` como argumento. A identidade viaja num ContextVar
que o portão (`asgi.McpGate`) preenche depois de validar o bearer no banco; o
SDK roda tools síncronas em thread com o contexto copiado, então a tool enxerga
exatamente a identidade da requisição que a disparou.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional

from app.mcp.errors import ErrorCode, McpToolError


@dataclass(frozen=True)
class McpIdentity:
    user_id: int
    grant_id: int
    client_pk: int
    client_id: str
    client_name: str
    scopes: frozenset[str]
    request_id: str
    #: `clientInfo` declarado pelo cliente (nome/versão) — só para auditoria.
    client_info: Optional[str] = None

    def has(self, scope: str) -> bool:
        return scope in self.scopes

    @property
    def origin(self) -> str:
        """Valor de `AuditLog.origin` para o que esta conexão alterar."""
        return f"mcp:{self.client_name}"[:80]


_current: ContextVar[Optional[McpIdentity]] = ContextVar("mcp_identity", default=None)


def set_identity(identity: Optional[McpIdentity]):
    return _current.set(identity)


def reset_identity(token) -> None:
    _current.reset(token)


def current_identity() -> McpIdentity:
    identity = _current.get()
    if identity is None:
        raise McpToolError(ErrorCode.AUTHENTICATION_REQUIRED, "Autenticação necessária.")
    return identity


def peek_identity() -> Optional[McpIdentity]:
    return _current.get()
