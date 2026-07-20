from contextvars import ContextVar
from typing import Optional

# ContextVar to store the current user ID globally within the request context
user_id_context: ContextVar[Optional[int]] = ContextVar("user_id", default=None)

def set_current_user_id(user_id: Optional[int]) -> None:
    user_id_context.set(user_id)

def get_current_user_id() -> Optional[int]:
    return user_id_context.get()
