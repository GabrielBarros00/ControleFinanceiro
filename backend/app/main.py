import time
import uuid

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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


def _promove_superadmin() -> None:
    """Garante que `SUPERADMIN_EMAIL` seja superadmin (ADR 0026).

    Idempotente e silencioso quando não há o que fazer. Roda a cada boot de
    propósito: é o único caminho de recuperação se o papel for perdido — um
    rebaixamento indevido, uma restauração de dump anterior à promoção — e um
    site sem superadmin não tem como se consertar pela própria interface.

    NÃO cria a conta. Promover um e-mail que ainda não se cadastrou seria criar
    usuário sem senha a partir de uma variável de ambiente; quem se cadastra é a
    pessoa, e a exceção de bootstrap em `auth.register` deixa ela passar.
    """
    if not settings.SUPERADMIN_EMAIL:
        return

    from sqlmodel import Session, select
    from app.db.session import engine
    from app.models.user import PlatformRole, User

    alvo = settings.SUPERADMIN_EMAIL.strip().lower()
    try:
        with Session(engine) as session:
            user = session.exec(select(User).where(User.email == alvo)).first()
            if user is None or user.platform_role == PlatformRole.superadmin:
                return
            user.platform_role = PlatformRole.superadmin
            session.add(user)
            session.commit()
            logger.info("superadmin_promovido", email=alvo)
    except Exception:
        # Um banco fora do ar no instante do boot não pode impedir a API de subir:
        # o healthcheck já reporta o banco indisponível, e o container reiniciando
        # em laço por causa DISTO deixaria o operador sem `/health` para
        # diagnosticar. O próximo boot promove.
        logger.warning("superadmin_promocao_falhou", email=alvo, exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.APP_ENV == "development":
        _upgrade_database_to_head()
    _promove_superadmin()
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


# Caminhos que continuam no ar durante a manutenção. A lista é curta e cada
# entrada tem um motivo:
#
# - `/health`: é o healthcheck do container. Sem ele, ligar a manutenção faria o
#   Docker considerar o backend doente e reiniciá-lo em laço — a manutenção
#   derrubaria o serviço que ela deveria apenas pausar.
# - `/auth/`: o admin precisa CONSEGUIR ENTRAR para desligar o modo. Sem isto, a
#   única saída seria `docker compose exec` com SQL na mão, que é exatamente a
#   situação que a tela de Admin existe para eliminar.
# - `/admin/`: onde fica o botão de desligar.
_LIBERADOS_NA_MANUTENCAO = ("/api/v1/health", "/api/v1/auth/", "/api/v1/admin/")


@app.middleware("http")
async def maintenance_middleware(request: Request, call_next):
    """Modo manutenção: só administradores usam o site (ADR 0026).

    A leitura é do CACHE de `app_settings`, não do banco: este middleware roda em
    toda requisição, e uma consulta por requisição só para descobrir que a
    manutenção está desligada — que é o caso em 100% do tempo normal — seria um
    custo permanente para uma funcionalidade excepcional. O cache é preenchido na
    primeira leitura de qualquer rota e invalidado quando o admin grava.

    A checagem do PAPEL, sim, precisa do banco — mas só acontece quando a
    manutenção está ligada, e aí o custo é irrelevante porque quase ninguém está
    passando por aqui.
    """
    caminho = request.url.path
    if caminho.startswith(_LIBERADOS_NA_MANUTENCAO):
        return await call_next(request)

    from app.db.session import session_scope
    from app.services import app_settings

    try:
        ligada = app_settings.peek_cache("maintenance_mode")
        if ligada is None:
            # `session_scope` e não `Session(engine)`: é a sessão CURTA que o
            # WebSocket já usa, e é o seam que a suíte substitui pela sessão do
            # fixture. Abrindo a sessão na mão, o middleware falaria com o banco
            # de desenvolvimento durante os testes.
            with session_scope() as sessao:
                ligada = app_settings.get(sessao, "maintenance_mode")
    except Exception:
        # Banco fora do ar não pode ligar a manutenção por acidente: o padrão
        # seguro aqui é DESLIGADA. Quem reporta banco indisponível é o /health.
        ligada = False

    if not ligada:
        return await call_next(request)

    if _e_administrador(request):
        return await call_next(request)

    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "message": (
                    "O sistema está em manutenção. Tente novamente em alguns minutos."
                )
            }
        },
    )


def _e_administrador(request: Request) -> bool:
    """Lê o papel do portador do cookie, sem depender das dependências da rota.

    Middleware roda ANTES do sistema de `Depends`, então não há `current_user`
    aqui — é preciso decodificar o token na mão. Qualquer falha (sem cookie,
    token inválido, expirado, usuário sumido) responde `False`: durante a
    manutenção, "não consegui provar que é admin" e "não é admin" levam ao mesmo
    lugar, e essa é a resposta segura.
    """
    from app.core.jwt import decode_token
    from app.db.session import session_scope
    from app.models.user import PlatformRole, User, platform_level

    token = request.cookies.get("access_token")
    if not token:
        return False
    try:
        payload = decode_token(token)
        user_id = int(payload.get("sub"))
        with session_scope() as sessao:
            user = sessao.get(User, user_id)
            return (
                user is not None
                and user.deleted_at is None
                and user.is_active
                and platform_level(user.platform_role) >= platform_level(PlatformRole.admin)
            )
    except Exception:
        return False


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
