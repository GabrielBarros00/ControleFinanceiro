"""A migração da integração MCP (ADR 0035) contra um banco POVOADO.

Em banco vazio o `user.public_id NOT NULL UNIQUE` passa sem provar nada. O que a
revisão promete é o backfill: cada usuário que JÁ existe ganha um id opaco
próprio (o `profile_get` depende dele), e só depois a coluna vira obrigatória e
única. Um backfill com o mesmo valor para todos, ou que deixasse alguém de fora,
derrubaria o upgrade em produção — ou pior, daria a duas pessoas o mesmo
"id estável" que o ChatGPT usa para distinguir contas.

E o `downgrade` tem de devolver o banco à revisão anterior sem perder o que já
existia (os usuários continuam lá; só as tabelas novas somem).

Alembic por SUBPROCESSO e banco descartável, como os demais testes de migração.
"""
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa

BACKEND_DIR = Path(__file__).resolve().parents[1]
REVISAO_ANTERIOR = "f2b6d41a9c03"
AGORA = "2026-09-01 12:00:00"
TABELAS_NOVAS = {
    "oauthclient", "oauthgrant", "oauthauthorizationcode", "oauthtoken",
    "mcptoolcall", "mcpoperation", "mcpconfirmation",
}


def _alembic(url: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": url, "APP_ENV": "test"}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def _roda(url: str, *args: str) -> None:
    r = _alembic(url, *args)
    assert r.returncode == 0, f"alembic {' '.join(args)} falhou:\n{r.stdout}\n{r.stderr}"


@pytest.fixture(scope="module")
def url_descartavel(tmp_path_factory):
    alvo = os.environ.get("TEST_DATABASE_URL", "")
    if not alvo.startswith("postgres"):
        arquivo = tmp_path_factory.mktemp("mig_mcp") / "mcp.db"
        yield f"sqlite:///{arquivo.as_posix()}"
        return
    nome = f"migmcp_{uuid.uuid4().hex[:12]}"
    admin = sa.create_engine(alvo, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{nome}"'))
    try:
        yield alvo.rsplit("/", 1)[0] + "/" + nome
    finally:
        with admin.connect() as conn:
            conn.execute(sa.text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :n AND pid <> pg_backend_pid()"
            ), {"n": nome})
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{nome}"'))
        admin.dispose()


def test_backfill_do_public_id_e_downgrade(url_descartavel):
    _roda(url_descartavel, "upgrade", REVISAO_ANTERIOR)
    engine = sa.create_engine(url_descartavel)
    try:
        with engine.begin() as conn:
            for i in range(3):
                conn.execute(sa.text(
                    'INSERT INTO "user" (name, email, is_active, password_hash, created_at,'
                    " updated_at, needs_onboarding, report_currency)"
                    " VALUES (:n, :e, TRUE, 'x', :agora, :agora, FALSE, 'BRL')"
                ), {"n": f"Pessoa {i}", "e": f"p{i}@example.com", "agora": AGORA})

        _roda(url_descartavel, "upgrade", "head")
        insp = sa.inspect(engine)
        assert TABELAS_NOVAS <= set(insp.get_table_names())
        assert "origin" in {c["name"] for c in insp.get_columns("auditlog")}
        with engine.connect() as conn:
            ids = [r[0] for r in conn.execute(sa.text('SELECT public_id FROM "user" ORDER BY id'))]
        assert len(ids) == 3 and len(set(ids)) == 3
        assert all(i and i.startswith("usr_") and len(i) == 28 for i in ids)
        # NOT NULL de verdade depois do backfill.
        coluna = next(c for c in sa.inspect(engine).get_columns("user") if c["name"] == "public_id")
        assert coluna["nullable"] is False

        _roda(url_descartavel, "downgrade", REVISAO_ANTERIOR)
        engine.dispose()
        insp = sa.inspect(engine)
        assert not TABELAS_NOVAS & set(insp.get_table_names())
        assert "public_id" not in {c["name"] for c in insp.get_columns("user")}
        with engine.connect() as conn:
            assert conn.execute(sa.text('SELECT count(*) FROM "user"')).scalar_one() == 3

        # E volta de novo, sem tropeçar no que o downgrade deixou.
        _roda(url_descartavel, "upgrade", "head")
    finally:
        engine.dispose()
