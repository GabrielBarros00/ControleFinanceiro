import os

# Antes de importar o app: testes gerenciam o próprio schema (create_all da
# metadata) — o auto-upgrade Alembic do lifespan é só para dev real (ADR 0005)
os.environ.setdefault("APP_ENV", "test")

# O fuso é premissa dos testes de virada de mês, não detalhe de ambiente. Ele
# vinha do default de `core/config.py`, então a suíte inteira de fronteira
# passava por acidente: bastaria alguém trocar o default — ou rodar com `TZ`
# setado — para os testes que exigem "31 de julho" começarem a exigir outro dia
# sem que nada no arquivo dissesse por quê. Fuso NEGATIVO de propósito: é o que
# expõe a diferença entre um instante e uma data civil.
os.environ.setdefault("APP_TIMEZONE", "America/Sao_Paulo")

from contextlib import contextmanager

import pytest
from sqlmodel import Session, SQLModel, create_engine
from app.db.session import get_session
from app.main import app
from app.core.config import settings
from app.core.rate_limit import account_limiter, auth_limiter

# Todos os models, para a metadata estar completa antes do create_all
# (a lista vive em app/models/__init__.py)
from app import models  # noqa: F401
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole

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


@pytest.fixture(scope="session", autouse=True)
def fecha_o_engine():
    """Devolve as conexões ao fim da suíte.

    O engine é de MÓDULO (criado na importação do conftest) e nada o fechava: no
    SQLite com `StaticPool` isso é uma conexão viva do começo ao fim, coletada
    pelo interpretador na saída sem passar por `close()`. O resultado era um
    `ResourceWarning: unclosed database` depois de uma suíte verde — barulho que
    não reprova nada e, justamente por isso, esconde o próximo vazamento de
    verdade. Contra Postgres, é a conexão do pool que fica pendurada.
    """
    yield
    engine.dispose()


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
def cadastro_aberto_por_padrao(db_session):
    """A suíte cria usuários pela porta ABERTA, e diz isso em voz alta.

    O padrão de produção é `invite_only` (ADR 0026), e as ~20 chamadas a
    `/auth/register` espalhadas pela suíte usam o cadastro como ATALHO para
    fabricar um usuário — não estão testando o portão. Sem esta fixture todas
    passariam a receber 403, e a correção óbvia (mudar o padrão para `open`)
    seria a errada: faria o desenvolvimento e o CI provarem um comportamento que
    produção não tem.

    Então a suíte abre a porta explicitamente. `tests/api/test_registration_modes.py`
    grava o próprio valor em cada teste, sobrescrevendo este — é lá, e só lá, que
    o portão é exercitado.

    O cache também é limpo: ele é de PROCESSO e sobreviveria ao `DELETE` das
    tabelas entre testes, fazendo um teste enxergar a configuração do anterior.
    """
    from app.services import app_settings

    app_settings.invalidate_cache()
    app_settings.set_value(db_session, "registration_mode", app_settings.RegistrationMode.open)
    db_session.commit()
    yield
    app_settings.invalidate_cache()


@pytest.fixture(autouse=True)
def isolar_armazenamento_de_anexos(tmp_path_factory, monkeypatch):
    """O conteúdo dos anexos vive FORA do banco (ADR 0007), então limpar as
    tabelas entre testes não basta: sem isto a suíte escreveria no diretório real
    de anexos e um teste enxergaria o arquivo do anterior (o armazenamento é
    endereçado por conteúdo — mesmo PNG, mesma chave)."""
    destino = tmp_path_factory.mktemp("anexos")
    monkeypatch.setattr(settings, "ATTACHMENT_STORAGE_DIR", str(destino))
    yield


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
    # O middleware de manutenção também não pode usar `Depends` — ele roda antes
    # do sistema de dependências. Ele importa `session_scope` de `app.db.session`
    # dentro da função, então substituir aqui, na origem, alcança as duas
    # chamadas (o modo em si e a checagem de papel). Sem isto o middleware
    # conversaria com o banco de DESENVOLVIMENTO no meio da suíte.
    monkeypatch.setattr("app.db.session.session_scope", scope_override)

    yield
    app.dependency_overrides.clear()
