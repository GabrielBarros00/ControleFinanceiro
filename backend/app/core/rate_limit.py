import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from app.core.config import settings


class RateLimiter:
    """Rate limiter em memória com janela deslizante (por processo).

    Suficiente para o deploy single-process (uvicorn --workers 1). Se o app
    escalar horizontalmente, trocar por um backend compartilhado (Redis).
    """

    # Varre chaves expiradas a cada N checagens permitidas, para o dicionário não
    # crescer sem limite com IPs/rotas únicos (RATE-001).
    _SWEEP_EVERY = 500

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._checks_since_sweep = 0

    def check(self, key: str) -> None:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if len(hits) >= self.max_requests:
            raise HTTPException(
                status_code=429,
                detail="Muitas tentativas. Aguarde um minuto e tente novamente."
            )
        hits.append(now)
        self._maybe_sweep(now)

    def _maybe_sweep(self, now: float) -> None:
        self._checks_since_sweep += 1
        if self._checks_since_sweep < self._SWEEP_EVERY:
            return
        self._checks_since_sweep = 0
        cutoff = now - self.window
        # Remove chaves cujo hit mais recente já expirou (deque vazio ou antigo)
        stale = [k for k, dq in self._hits.items() if not dq or dq[-1] <= cutoff]
        for k in stale:
            del self._hits[k]

    def reset(self) -> None:
        self._hits.clear()
        self._checks_since_sweep = 0


# 5 tentativas por minuto por IP+rota (login, register, forgot-password)
auth_limiter = RateLimiter(max_requests=5, window_seconds=60)


def rate_limit_auth(request: Request) -> None:
    """Dependency de rate limiting para endpoints sensíveis de auth.

    Usa request.client.host — atrás do nginx, o uvicorn roda com
    --proxy-headers para que o IP real chegue aqui.
    """
    if not settings.RATE_LIMIT_ENABLED:
        return
    client_ip = request.client.host if request.client else "unknown"
    auth_limiter.check(f"{client_ip}:{request.url.path}")
