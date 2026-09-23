"""Teto de uso por conexão de IA (pessoa + cliente), com custo por tool.

Um agente em laço pode disparar centenas de chamadas por minuto sem ninguém
perceber — e cada busca ou relatório custa consultas de verdade no banco de um
app de 1 worker. O balde é por PESSOA + CLIENTE: dois agentes da mesma pessoa não
disputam cota, e o mesmo agente não escapa trocando de IP (o IP de quem chama é o
data center do ChatGPT/Claude, compartilhado por todo mundo).

Dois limites: unidades por minuto (leitura 1, busca/relatório 2, escrita 3,
massa 5) e escritas por minuto. Em memória, como os demais do app: correto para o
deploy de 1 processo (o seam para Redis é este módulo).
"""
from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque

from app.core.config import settings
from app.mcp.errors import ErrorCode, McpToolError


class CostLimiter:
    def __init__(self, window_seconds: int = 60):
        self.window = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, cost: int, limit: int) -> None:
        agora = time.monotonic()
        with self._lock:
            fila = self._hits[key]
            while fila and fila[0][0] <= agora - self.window:
                fila.popleft()
            usado = sum(c for _, c in fila)
            if usado + cost > limit:
                espera = max(1, math.ceil(fila[0][0] + self.window - agora)) if fila else self.window
                raise McpToolError(
                    ErrorCode.RATE_LIMITED,
                    "Muitas chamadas em pouco tempo para esta conexão. Aguarde e tente de novo.",
                    retry_after=espera,
                )
            fila.append((agora, cost))

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


units_limiter = CostLimiter()
writes_limiter = CostLimiter()


def check(user_id: int, client_pk: int, *, cost: int, is_write: bool) -> None:
    if not settings.RATE_LIMIT_ENABLED:
        return
    chave = f"{user_id}:{client_pk}"
    units_limiter.check(chave, cost, settings.MCP_RATE_LIMIT_UNITS_PER_MINUTE)
    if is_write:
        writes_limiter.check(chave, 1, settings.MCP_WRITE_RATE_LIMIT_PER_MINUTE)


def reset() -> None:
    units_limiter.reset()
    writes_limiter.reset()
