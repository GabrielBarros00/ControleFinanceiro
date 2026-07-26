import os

# Antes de importar o app: testes gerenciam o próprio schema (create_all da
# metadata) — o auto-upgrade Alembic do lifespan é só para dev real (ADR 0005)
os.environ.setdefault("APP_ENV", "test")

from contextlib import contextmanager

import pytest
from sqlmodel import Session, SQLModel, create_engine
from app.db.session import get_session
from app.main import app
from app.core.rate_limit import account_limiter, auth_limiter

# Import all models to ensure metadata is complete before create_all
from app.models.user import User  # noqa: F401
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole, WorkspaceInvite  # noqa: F401
from app.models.transaction import Transaction, TransactionPayer, TransactionSplit, TransactionItem  # noqa: F401
from app.models.recurring import RecurringExpense, RecurringIncome  # noqa: F401
from app.models.audit import AuditLog  # noqa: F401
from app.models.income import Income  # noqa: F401
from app.models.credit_card import CreditCard, CardStatement  # noqa: F401
from app.models.category import Category  # noqa: F401
from app.models.estimate import MonthlyEstimate  # noqa: F401
from app.models.financing import Financing, AmortizationInstallment  # noqa: F401
from app.models.sync_event import SyncEvent  # noqa: F401
from app.models.settlement import Settlement  # noqa: F401
from app.models.attachment import Attachment  # noqa: F401
from app.models.tag import Tag, TransactionTagLink  # noqa: F401
from app.models.payment_account import PaymentAccount  # noqa: F401
from app.models.import_batch import ImportBatch, ImportRow  # noqa: F401
from app.models.refresh_session import RefreshSession  # noqa: F401
from app.models.exchange_rate import ExchangeRate  # noqa: F401

from sqlalchemy.pool import StaticPool

# Default: SQLite em memória (StaticPool compartilha a conexão).
# TEST_DATABASE_URL permite rodar a MESMA suíte contra Postgres (leg do CI).
test_db_url = os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:")
if test_db_url.startswith("sqlite"):
    engine = create_engine(
        test_db_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
else:
    engine = create_engine(test_db_url)

_schema_ready = False


@pytest.fixture(name="db_session")
def session_fixture():
    # Schema criado UMA vez por processo; entre testes só apagamos os dados
    # (DELETE em ordem reversa de dependência). Sem DDL por teste, a suíte
    # roda em segundos também contra Postgres.
    global _schema_ready
    if not _schema_ready:
        SQLModel.metadata.create_all(engine)
        _schema_ready = True
    with Session(engine) as session:
        yield session
    with engine.begin() as conn:
        for table in reversed(SQLModel.metadata.sorted_tables):
            conn.execute(table.delete())

@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Evita que os rate limits de auth acumulem entre testes (IP e conta)."""
    auth_limiter.reset()
    account_limiter.reset()
    yield
    auth_limiter.reset()
    account_limiter.reset()


@pytest.fixture(autouse=True)
def reset_audit_context():
    """O contexto de auditoria não pode vazar entre testes: um user_id
    fantasma viraria FK inválida no auditlog (Postgres aplica FKs)."""
    from app.core.context import set_current_user_id
    set_current_user_id(None)
    yield
    set_current_user_id(None)

from app.core.jwt import create_access_token

@pytest.fixture(name="setup_data")
def setup_data_fixture(db_session: Session):
    # Users
    u1 = User(name="User 1", email="u1@example.com", password_hash="hash")
    u2 = User(name="User 2", email="u2@example.com", password_hash="hash")
    db_session.add_all([u1, u2])
    db_session.commit()
    db_session.refresh(u1)
    db_session.refresh(u2)
    
    # Workspaces
    ws1 = Workspace(name="WS1", created_by_user_id=u1.id)
    ws2 = Workspace(name="WS2", created_by_user_id=u2.id)
    db_session.add_all([ws1, ws2])
    db_session.commit()
    db_session.refresh(ws1)
    db_session.refresh(ws2)
    
    # Memberships
    db_session.add(WorkspaceMembership(workspace_id=ws1.id, user_id=u1.id, role=WorkspaceRole.owner))
    db_session.add(WorkspaceMembership(workspace_id=ws2.id, user_id=u2.id, role=WorkspaceRole.owner))
    db_session.commit()
    
    # Tokens
    t1 = create_access_token(data={"sub": str(u1.id)})
    t2 = create_access_token(data={"sub": str(u2.id)})
    
    return {
        "u1": u1, "u2": u2,
        "ws1": ws1, "ws2": ws2,
        "headers1": {"Cookie": f"access_token={t1}"},
        "headers2": {"Cookie": f"access_token={t2}"}
    }

@pytest.fixture(name="seed_ws")
def seed_ws_fixture(db_session):
    """User + Workspace reais para testes de domínio (FKs válidas no Postgres)."""
    user = User(name="Seed User", email="seed@test.com", password_hash="hash")
    ws = Workspace(name="Seed WS")
    db_session.add_all([user, ws])
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(ws)
    return {"user": user, "ws": ws}


@pytest.fixture(name="override_get_session")
def override_get_session_fixture(db_session: Session, monkeypatch):
    def get_session_override():
        yield db_session
    app.dependency_overrides[get_session] = get_session_override

    # O WebSocket NÃO usa Depends: a sessão dele precisa ser curta, senão prende
    # uma conexão do pool enquanto o socket estiver aberto (uma por aba). O seam
    # de teste dele é o session_scope — substituído aqui pela mesma sessão do
    # fixture, para o socket enxergar o banco do teste.
    @contextmanager
    def scope_override():
        yield db_session
    monkeypatch.setattr("app.ws.routes.session_scope", scope_override)

    yield
    app.dependency_overrides.clear()
