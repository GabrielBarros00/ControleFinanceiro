"""A migração da medida do item (ADR 0040) contra um banco POVOADO.

Ampliar `unit_amount` de 2 para 4 casas não pode tocar no que já existe, e a
coluna nova tem de nascer vazia (a linha antiga não tem medida — inventar "un"
seria afirmar algo que ninguém informou). E o motivo de existir: depois dela, o
preço de R$ 5,899 o litro volta do banco como 5,899, não 5,90.

Alembic por SUBPROCESSO e banco descartável pelos mesmos motivos de
`test_migration_a4e8c1b90f52.py`.
"""
import os
import subprocess
import sys
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa

BACKEND_DIR = Path(__file__).resolve().parents[1]
REVISAO_ANTERIOR = "e5a9c2d4b7f1"
AGORA = "2026-09-01 12:00:00"


def _alembic(url: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": url, "APP_ENV": "test"}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=BACKEND_DIR, env=env,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def _upgrade(url: str, revisao: str) -> None:
    resultado = _alembic(url, "upgrade", revisao)
    assert resultado.returncode == 0, f"upgrade para {revisao} falhou:\n{resultado.stdout}\n{resultado.stderr}"


@pytest.fixture(scope="module")
def url_descartavel(tmp_path_factory):
    alvo = os.environ.get("TEST_DATABASE_URL", "")
    if not alvo.startswith("postgres"):
        yield f"sqlite:///{(tmp_path_factory.mktemp('mig_medida') / 'medida.db').as_posix()}"
        return
    nome = f"migmd_{uuid.uuid4().hex[:12]}"
    admin = sa.create_engine(alvo, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{nome}"'))
    try:
        yield alvo.rsplit("/", 1)[0] + "/" + nome
    finally:
        with admin.connect() as conn:
            conn.execute(sa.text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :n AND pid <> pg_backend_pid()"
            ), {"n": nome})
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{nome}"'))
        admin.dispose()


@pytest.fixture(scope="module")
def banco(url_descartavel):
    _upgrade(url_descartavel, REVISAO_ANTERIOR)
    engine = sa.create_engine(url_descartavel)
    with engine.begin() as conn:
        def novo(sql: str, **params) -> int:
            return conn.execute(sa.text(sql + " RETURNING id"), params).scalar_one()

        user = novo(
            'INSERT INTO "user" (name, email, is_active, password_hash, created_at, updated_at,'
            " public_id, needs_onboarding, report_currency)"
            " VALUES ('Dona', 'medida@example.com', TRUE, 'x', :a, :a, :pid, FALSE, 'BRL')",
            a=AGORA, pid=uuid.uuid4().hex,
        )
        ws = novo(
            "INSERT INTO workspace (name, created_at, updated_at, event_seq, base_currency)"
            " VALUES ('Casa', :a, :a, 0, 'BRL')", a=AGORA,
        )
        tx = novo(
            "INSERT INTO \"transaction\" (title, currency, total_amount, transaction_date, status,"
            " workspace_id, created_by_user_id, created_at, updated_at)"
            " VALUES ('Mercado', 'BRL', 80.00, :a, 'confirmed', :ws, :u, :a, :a)",
            a=AGORA, ws=ws, u=user,
        )
        for titulo, valor, qtd, unit in (("Refrigerante", "50.00", "2", "25.00"), ("Pão", "30.00", "1", None)):
            conn.execute(sa.text(
                "INSERT INTO transactionitem (transaction_id, title, amount, quantity, unit_amount,"
                " position, created_at, updated_at) VALUES (:tx, :t, :v, :q, :un, 0, :a, :a)"
            ), {"tx": tx, "t": titulo, "v": valor, "q": qtd, "un": unit, "a": AGORA})
    _upgrade(url_descartavel, "head")
    yield engine, tx
    engine.dispose()


def test_o_que_ja_existia_fica_intacto_e_sem_unidade(banco):
    engine, tx = banco
    with engine.connect() as conn:
        linhas = conn.execute(sa.text(
            "SELECT title, amount, quantity, unit_amount, unit FROM transactionitem"
            " WHERE transaction_id = :tx ORDER BY title"
        ), {"tx": tx}).all()
    assert [(t, Decimal(str(v)), Decimal(str(q)), None if u is None else Decimal(str(u)), un)
            for t, v, q, u, un in linhas] == [
        ("Pão", Decimal("30.00"), Decimal("1"), None, None),
        ("Refrigerante", Decimal("50.00"), Decimal("2"), Decimal("25"), None),
    ]


def test_o_preco_do_litro_volta_com_tres_casas(banco):
    engine, tx = banco
    with engine.begin() as conn:
        conn.execute(sa.text(
            "INSERT INTO transactionitem (transaction_id, title, amount, quantity, unit_amount, unit,"
            " position, created_at, updated_at)"
            " VALUES (:tx, 'Gasolina', 236.69, 40.123, 5.899, 'l', 1, :a, :a)"
        ), {"tx": tx, "a": AGORA})
        unitario, unidade = conn.execute(sa.text(
            "SELECT unit_amount, unit FROM transactionitem WHERE title = 'Gasolina'"
        )).one()
    assert (Decimal(str(unitario)), unidade) == (Decimal("5.899"), "l")
