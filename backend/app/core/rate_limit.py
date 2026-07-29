import time
from collections import defaultdict, deque
from typing import Optional

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


# 10 tentativas por minuto POR CONTA, somando todas as origens
account_limiter = RateLimiter(max_requests=10, window_seconds=60)


# Rotas que fazem I/O EXTERNO síncrono. A consulta de câmbio pode disparar duas
# buscas na fonte, e o PTAX faz look-back de 5 dias — o pior caso são ~10
# requisições de saída, cada uma com EXCHANGE_RATE_TIMEOUT_SECONDS. Num backend
# de 1 worker (restrição do ConnectionManager de WS) isso ocupa uma thread do
# pool do Starlette por dezenas de segundos; algumas chamadas simultâneas com
# códigos de moeda variados (cache miss garantido) congelam a API inteira.
outbound_limiter = RateLimiter(max_requests=30, window_seconds=60)


def rate_limit_outbound(key: str) -> None:
    """Teto para rotas que podem ir à rede. Chaveado por workspace+rota."""
    if not settings.RATE_LIMIT_ENABLED:
        return
    outbound_limiter.check(f"out:{key}")


def rate_limit_auth(request: Request) -> None:
    """Dependency de rate limiting para endpoints sensíveis de auth.

    Usa request.client.host — atrás do nginx, o uvicorn roda com
    --proxy-headers para que o IP real chegue aqui.
    """
    if not settings.RATE_LIMIT_ENABLED:
        return
    client_ip = request.client.host if request.client else "unknown"
    auth_limiter.check(f"{client_ip}:{request.url.path}")


def rate_limit_account(email: Optional[str], path: str) -> None:
    """Segundo balde, chaveado pela CONTA alvo.

    O balde por IP sozinho é contornável: o uvicorn roda com
    `--forwarded-allow-ips`, então quem alcançar o backend diretamente pode
    forjar `X-Forwarded-For` e ganhar um balde novo a cada valor inventado —
    força bruta sem teto. Amarrado à conta, o custo do ataque não depende de
    quantos IPs o atacante consegue simular.

    Chamado DEPOIS de validar o corpo (precisa do e-mail), então complementa —
    não substitui — o balde por IP.
    """
    if not settings.RATE_LIMIT_ENABLED or not email:
        return
    account_limiter.check(f"acct:{email.strip().lower()}:{path}")
