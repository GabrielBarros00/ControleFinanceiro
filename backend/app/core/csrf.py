"""Proteção CSRF por validação de Origin/Referer (SEC-002).

Cookies SameSite=Lax mitigam parte dos ataques, mas não substituem a checagem
explícita: em métodos mutantes, se o navegador enviou Origin (ou Referer), a
origem PRECISA estar na lista permitida (CORS_ORIGINS + FRONTEND_URL — em
produção inclua a origem pública do site no .env). Requisições sem nenhum dos
dois cabeçalhos (curl, testes, server-to-server) passam: navegadores sempre
enviam Origin em mutações cross-origin, que é o vetor do CSRF.
"""
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.config import settings

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _allowed_origins() -> set:
    origins = {o.rstrip("/") for o in settings.cors_origins_list}
    origins.add(settings.FRONTEND_URL.rstrip("/"))
    return origins


async def csrf_origin_middleware(request: Request, call_next):
    if request.method in MUTATING_METHODS:
        source = request.headers.get("origin")
        if not source:
            referer = request.headers.get("referer")
            if referer:
                parts = urlsplit(referer)
                source = f"{parts.scheme}://{parts.netloc}" if parts.netloc else referer
        if source and source.rstrip("/") not in _allowed_origins():
            # Mesmo envelope de erro dos handlers ({"error": {...}})
            return JSONResponse(
                status_code=403,
                content={"error": {
                    "code": "FORBIDDEN",
                    "message": "Origem da requisição não permitida",
                    "details": {},
                }},
            )
    return await call_next(request)
