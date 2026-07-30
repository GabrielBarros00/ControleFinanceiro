import time
import uuid

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.api.router import router
from app.core.config import settings
from app.api.errors import (
    validation_exception_handler,
    http_exception_handler,
    internal_server_error_handler
)
from app.services.event_service import register_event_listeners
from app.ws.manager import manager as ws_manager

# Import all models to ensure they are registered with SQLModel.metadata
from app import models  # noqa: F401

from contextlib import asynccontextmanager

# Logging estruturado: JSON em produção (agregável), console legível em dev
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        (
            structlog.processors.JSONRenderer()
            if settings.is_deployed
            else structlog.dev.ConsoleRenderer()
        ),
    ],
)

logger = structlog.get_logger("app.http")

# Entrega de eventos WS após commit (registro idempotente, uma vez por processo)
register_event_listeners()

def _upgrade_database_to_head() -> None:
    """Alembic é a ÚNICA interface de evolução de schema (ADR 0005).

    Em dev o upgrade roda no startup por conveniência (banco novo nasce no
    head; banco existente é no-op). Em produção o entrypoint do container
    já roda `alembic upgrade head` — aqui não fazemos nada.
    """
    from pathlib import Path
    from alembic import command
    from alembic.config import Config

    backend_dir = Path(__file__).resolve().parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.APP_ENV == "development":
        _upgrade_database_to_head()
    ws_manager.startup()
    yield
    await ws_manager.shutdown()

# Docs, CSP e log JSON valem em produção E staging: staging é deploy real
# servindo gente, não ambiente de desenvolvimento (ver Settings.is_deployed).
_is_deployed = settings.is_deployed

app = FastAPI(
    title="Controle Financeiro V4",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    # Docs/OpenAPI ficam FORA do ar em produção/staging (SEC-006): não expõem o mapa
    # da API nem carregam scripts de CDN
    docs_url=None if _is_deployed else "/docs",
    redoc_url=None if _is_deployed else "/redoc",
    openapi_url=None if _is_deployed else "/openapi.json",
)

# TrustedHost em produção: recusa requisições com Host forjado (SEC-006).
# "*" (padrão) desliga a checagem — o operador restringe via ALLOWED_HOSTS.
if settings.allowed_hosts_list and settings.allowed_hosts_list != ["*"]:
    from starlette.middleware.trustedhost import TrustedHostMiddleware
    # localhost/127.0.0.1 entram sempre: o healthcheck interno do container bate em
    # http://localhost:8000/api/v1/health e seria recusado por um Host restrito
    hosts = list(dict.fromkeys(settings.allowed_hosts_list + ["localhost", "127.0.0.1"]))
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)

# Configuração de CORS (origens vêm das settings)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


from app.core.csrf import csrf_origin_middleware  # noqa: E402

app.middleware("http")(csrf_origin_middleware)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault(
        "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
    )
    # CSP restritiva em produção/staging (a API só serve JSON; em dev o /docs precisa
    # de scripts de CDN e ficaria quebrado com default-src 'none')
    if _is_deployed:
        response.headers.setdefault(
            "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
        )
    return response


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    logger.info(
        "http_request",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=duration_ms,
    )
    response.headers["X-Request-ID"] = request_id
    return response


# Registro de Handlers de Erro customizados
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(Exception, internal_server_error_handler)

app.include_router(router)


@app.get("/")
async def root():
    return {"message": "Welcome to Controle Financeiro V4 API"}
