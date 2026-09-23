from contextvars import ContextVar
from typing import Optional

# ContextVar to store the current user ID globally within the request context
user_id_context: ContextVar[Optional[int]] = ContextVar("user_id", default=None)

# Por onde a mudança entrou. `None` = o próprio app (SPA/REST); "mcp:<cliente>"
# = um agente de IA pela integração MCP (ADR 0035). Vai para `AuditLog.origin`
# pelos listeners de auditoria, e é o que permite responder "essa alteração foi
# feita por uma integração?" olhando só a trilha.
request_origin_context: ContextVar[Optional[str]] = ContextVar("request_origin", default=None)

def set_current_user_id(user_id: Optional[int]) -> None:
    user_id_context.set(user_id)

def get_current_user_id() -> Optional[int]:
    return user_id_context.get()

def set_request_origin(origin: Optional[str]) -> None:
    request_origin_context.set(origin[:80] if origin else None)

def get_request_origin() -> Optional[str]:
    return request_origin_context.get()
