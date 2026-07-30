"""Invariantes sob concorrência REAL (F2).

O resto da suíte é sequencial, e o Playwright roda com `workers: 1` — nada no
projeto exercitava duas requisições ao mesmo tempo. Só que é exatamente aí que
mora a classe de bug das Ondas A e C: dedup lê-depois-escreve, `select` antes de
`insert`, `uses += 1` em Python. Todos passavam nos testes sequenciais.

Estes testes usam threads de verdade contra um banco de ARQUIVO (o padrão da
suíte é `:memory:` com StaticPool, que serializa tudo numa conexão só e
esconderia justamente o que queremos ver).

Marcados com `concurrency` para poderem ser isolados quando necessário.
"""
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, UTC
from decimal import Decimal
from typing import Callable, List

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.category import Category
from app.models.income import Income
from app.models.notification import Notification  # noqa: F401 (metadata)
from app.models.recurring import RecurringIncome
from app.models.user import User
from app.models.workspace import (
    Workspace,
    WorkspaceInvite,
    WorkspaceMembership,
    WorkspaceRole,
)
from app.services.membership_service import ensure_membership
from app.services.recurring_service import RecurringIncomeService

pytestmark = pytest.mark.concurrency

THREADS = 8


@pytest.fixture
def engine_arquivo():
    """Banco em ARQUIVO: o :memory: com StaticPool da suíte serializa tudo numa
    conexão única e esconderia a corrida que queremos provocar."""
    fd, caminho = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(
        f"sqlite:///{caminho}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    SQLModel.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()
        try:
            os.unlink(caminho)
        except OSError:
            pass


def _em_paralelo(engine, tarefa: Callable[[Session], object], n: int = THREADS) -> List[object]:
    """Roda `tarefa` em N threads, cada uma com a própria sessão."""
    def executar():
        with Session(engine) as session:
            try:
                resultado = tarefa(session)
                session.commit()
                return resultado
            except Exception as exc:  # a corrida perdida pode legitimamente falhar
                session.rollback()
                return exc

    with ThreadPoolExecutor(max_workers=n) as pool:
        return [f.result() for f in [pool.submit(executar) for _ in range(n)]]


@pytest.fixture
def base(engine_arquivo):
    with Session(engine_arquivo) as session:
        user = User(name="G", email="conc@t.com", password_hash="h")
        ws = Workspace(name="WS")
        session.add_all([user, ws])
        session.commit()
        session.refresh(user)
        session.refresh(ws)
        return {"engine": engine_arquivo, "user_id": user.id, "ws_id": ws.id}


# --- A1: renda recorrente ---------------------------------------------------


def test_renda_recorrente_nao_duplica_sob_concorrencia(base):
    """8 requisições simultâneas de LEITURA materializando o mesmo salário.

    É o cenário real: o Início dispara summary + reports + transactions em
    paralelo, e todos chamam ensure_and_commit.
    """
    engine = base["engine"]
    with Session(engine) as session:
        session.add(RecurringIncome(
            title="Salário", base_amount=Decimal("5000.00"), day_of_month=5,
            user_id=base["user_id"],
        ))
        session.commit()

    _em_paralelo(
        engine,
        lambda s: RecurringIncomeService.generate_due_income(
            s, base["ws_id"], date(2026, 7, 15), allow_fetch=False
        ),
    )

    with Session(engine) as session:
        rendas = session.exec(select(Income)).all()
    assert len(rendas) == 1, f"salário materializado {len(rendas)}x — deveria ser 1"


# --- A2: membership ---------------------------------------------------------


def test_membership_nao_duplica_sob_concorrencia(base):
    engine = base["engine"]
    _em_paralelo(
        engine,
        lambda s: ensure_membership(s, base["ws_id"], base["user_id"], WorkspaceRole.member),
    )

    with Session(engine) as session:
        vinculos = session.exec(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == base["ws_id"],
                WorkspaceMembership.user_id == base["user_id"],
            )
        ).all()
    assert len(vinculos) == 1, f"{len(vinculos)} memberships para o mesmo par"


def test_ensure_membership_devolve_um_unico_criador(base):
    """Exatamente UMA das threads pode reportar que criou — as outras devem
    receber False, não erro."""
    engine = base["engine"]
    resultados = _em_paralelo(
        engine,
        lambda s: ensure_membership(s, base["ws_id"], base["user_id"], WorkspaceRole.member),
    )
    assert not any(isinstance(r, Exception) for r in resultados), resultados
    assert sum(1 for r in resultados if r is True) == 1


# --- C12: categoria ---------------------------------------------------------


def test_categoria_nao_duplica_sob_concorrencia(base):
    engine = base["engine"]

    def criar(session: Session):
        session.add(Category(workspace_id=base["ws_id"], name="Mercado"))

    _em_paralelo(engine, criar)

    with Session(engine) as session:
        categorias = session.exec(
            select(Category).where(Category.name == "Mercado")
        ).all()
    assert len(categorias) == 1, f"{len(categorias)} categorias com o mesmo nome"


# --- C13: usos do convite por link ------------------------------------------


def test_convite_por_link_respeita_max_uses(base):
    """`invite.uses += 1` em Python deixava 8 threads lerem o mesmo valor."""
    engine = base["engine"]
    with Session(engine) as session:
        convite = WorkspaceInvite(
            workspace_id=base["ws_id"], email=None, role=WorkspaceRole.member,
            expires_at=datetime.now(UTC) + timedelta(days=7), max_uses=1,
        )
        session.add(convite)
        session.commit()
        session.refresh(convite)
        convite_id = convite.id

    from sqlalchemy import update

    def consumir(session: Session):
        return session.execute(
            update(WorkspaceInvite)
            .where(WorkspaceInvite.id == convite_id)
            .values(uses=WorkspaceInvite.uses + 1)
            .returning(WorkspaceInvite.uses)
        ).scalar_one()

    resultados = [r for r in _em_paralelo(engine, consumir) if not isinstance(r, Exception)]

    # O incremento atômico garante que cada thread veja um valor DISTINTO —
    # é isso que permite recusar quem passou do teto.
    assert len(set(resultados)) == len(resultados), (
        f"threads leram o mesmo contador: {sorted(resultados)}"
    )
    dentro_do_limite = [r for r in resultados if r <= 1]
    assert len(dentro_do_limite) == 1, "mais de uma thread ficou dentro do max_uses"
