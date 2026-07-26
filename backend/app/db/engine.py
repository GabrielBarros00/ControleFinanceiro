from sqlmodel import create_engine
from app.core.config import settings
from app.core.audit_events import register_audit_listeners

# Engine configurado via DATABASE_URL.
#
# SQLite (dev/teste): connect_args={"check_same_thread": False} é necessário no
# FastAPI. As opções de pool abaixo não se aplicam (o pool do SQLite em memória
# não as aceita).
#
# Postgres (produção): pool explícito. Sem `pool_pre_ping` uma conexão morta
# (reinício do banco, timeout de ociosidade, queda de rede) só era descoberta ao
# ser usada, e a API respondia 500 até o pool reciclar sozinho — o cenário mais
# comum de "o app caiu do nada". `pool_recycle` derruba conexões antes que
# qualquer intermediário as expire.
_engine_kwargs = {
    "echo": settings.SQL_ECHO,
}

if "sqlite" in settings.DATABASE_URL:
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    _engine_kwargs.update(
        pool_pre_ping=True,
        pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT_SECONDS,
    )

engine = create_engine(settings.DATABASE_URL, **_engine_kwargs)

# Register automated auditing listeners
register_audit_listeners()
