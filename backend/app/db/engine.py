from sqlmodel import create_engine
from app.core.config import settings
from app.core.audit_events import register_audit_listeners

# Engine configurado via DATABASE_URL
# connect_args={"check_same_thread": False} é necessário para o SQLite no FastAPI
engine = create_engine(
    settings.DATABASE_URL, 
    echo=settings.APP_ENV == "development",
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
)

# Register automated auditing listeners
register_audit_listeners()
