"""A migração da liquidação (ADR 0029) contra um banco POVOADO, não vazio.

`alembic upgrade head` em banco limpo passa sem provar nada: a migração adiciona
três colunas e um índice, e a única linha que importa — o `UPDATE` de backfill —
não tem nada para tocar.

O que ela promete é que **nenhum número do passado muda**. `settled_at` nasce nula
e o caixa passou a exigi-la; sem o backfill, o `cash_out` de todo mês já fechado
cairia a zero na primeira leitura depois do deploy. Meses que já foram conferidos,
exportados e usados para acertar contas entre pessoas.

Aqui o banco é semeado com lançamentos ANTES da revisão e se verifica, depois do
upgrade, que cada um ficou liquidado na própria data. E que os defaults das outras
duas colunas são os declarados: espaço com controle LIGADO, recorrência com débito
automático DESLIGADO — se fossem ao contrário, o ADR se aplicaria ao contrário.

Alembic por SUBPROCESSO e fixture de banco descartável pelos mesmos motivos de
`test_migration_c7e3b81f04a9.py` — ver o cabeçalho de lá.
"""
import os
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest
import sqlalchemy as sa

BACKEND_DIR = Path(__file__).resolve().parents[1]
REVISAO_ANTERIOR = "f2a6c93b571e"

AGORA = "2026-07-01 12:00:00"
# Três instantes distintos, de propósito: o backfill tem de copiar CADA data, não
# carimbar todas com o mesmo valor (um `SET settled_at = now()` passaria por um
# teste de uma linha só e reescreveria o mês de todas as outras).
DIA_5 = "2026-05-05 15:00:00"
DIA_20 = "2026-06-20 15:00:00"
NOITE_31 = "2026-08-01 01:00:00"  # 22h de 31/07 em São Paulo


def _alembic(url: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": url, "APP_ENV": "test"}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        # A saída tem acentos e o console do Windows não é UTF-8.
        encoding="utf-8",
        errors="replace",
    )


def _upgrade(url: str, revisao: str) -> subprocess.CompletedProcess:
    resultado = _alembic(url, "upgrade", revisao)
    assert resultado.returncode == 0, (
        f"upgrade para {revisao} falhou:\n{resultado.stdout}\n{resultado.stderr}"
    )
    return resultado


@pytest.fixture(scope="module")
def url_descartavel(tmp_path_factory):
    """Banco vazio e exclusivo deste módulo (arquivo no SQLite, database próprio
    no Postgres — o `TEST_DATABASE_URL` do CI já está na head)."""
    alvo = os.environ.get("TEST_DATABASE_URL", "")
    if not alvo.startswith("postgres"):
        arquivo = tmp_path_factory.mktemp("mig_liq") / "liquidacao.db"
        yield f"sqlite:///{arquivo.as_posix()}"
        return

    nome = f"migliq_{uuid.uuid4().hex[:12]}"
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
def banco_migrado(url_descartavel):
    """Sobe na revisão anterior, semeia lançamentos antigos, e sobe até a head.

    Até a HEAD, e não só até `a1c7e5b39d42`: com dados no banco, o que importa é a
    cadeia inteira sobreviver — é isso que o `alembic upgrade head` do Dockerfile
    faz em produção.
    """
    _upgrade(url_descartavel, REVISAO_ANTERIOR)
    engine = sa.create_engine(url_descartavel)
    with engine.begin() as conn:
        _semeia(conn)

    resultado = _upgrade(url_descartavel, "head")
    yield engine, resultado
    engine.dispose()


def _semeia(conn) -> None:
    def exec_(sql: str, **params):
        return conn.execute(sa.text(sql), params or {})

    def ids(sql: str, **params) -> int:
        return exec_(sql + " RETURNING id", **params).scalar_one()

    user = ids(
        'INSERT INTO "user" (name, email, is_active, password_hash, created_at,'
        " updated_at, needs_onboarding, report_currency)"
        " VALUES ('Dona', 'liquidacao@example.com', TRUE, 'x', :agora, :agora, FALSE, 'BRL')",
        agora=AGORA,
    )
    ws = ids(
        "INSERT INTO workspace (name, created_at, updated_at, event_seq, base_currency)"
        " VALUES ('Casa', :agora, :agora, 0, 'BRL')",
        agora=AGORA,
    )
    exec_(
        "INSERT INTO recurringexpense"
        " (title, base_amount, frequency, \"interval\", day_of_month, is_active,"
        "  workspace_id, created_by_user_id, currency, created_at, updated_at)"
        " VALUES ('Aluguel', 1000, 'monthly', 1, 1, TRUE, :ws, :u, 'BRL', :agora, :agora)",
        ws=ws, u=user, agora=AGORA,
    )

    def despesa(titulo: str, quando: str, mes: str) -> int:
        return ids(
            'INSERT INTO "transaction"'
            " (title, currency, total_amount, transaction_date, status, workspace_id,"
            "  created_at, updated_at, split_mode, billing_month)"
            " VALUES (:t, 'BRL', 100, :quando, 'confirmed', :ws, :agora, :agora,"
            "         'transaction', :mes)",
            t=titulo, quando=quando, ws=ws, mes=mes, agora=AGORA,
        )

    despesa("Mercado de maio", DIA_5, "2026-05")
    despesa("Farmácia de junho", DIA_20, "2026-06")
    # Instante na borda do mês: a cópia é literal, então ele continua sendo o
    # mesmo instante — a migração não pode "arredondar" nada.
    despesa("Padaria da noite", NOITE_31, "2026-07")


def _datas(engine, sql: str, coluna: str, **params) -> list:
    """Lê uma coluna de data DECLARANDO o tipo.

    Sem tipo, o driver do SQLite devolve `str` e as asserções comparariam
    `'2026-05-05 15:00:00.000000'` com um `datetime`, falhando em todo cenário —
    inclusive nos que a migração acertou.
    """
    with engine.connect() as conn:
        linhas = conn.execute(
            sa.text(sql).columns(sa.column(coluna, sa.DateTime())), params
        ).fetchall()
    return [linha[0] for linha in linhas]


# ---------------------------------------------------------------------------
# A promessa: o passado não muda

def test_todo_lancamento_antigo_fica_liquidado_na_propria_data(banco_migrado):
    """O ponto da migração. Sem este `UPDATE`, o caixa de todo mês fechado
    cairia a zero na primeira leitura depois do deploy."""
    engine, _ = banco_migrado
    pares = _datas(
        engine,
        'SELECT settled_at FROM "transaction" ORDER BY billing_month',
        "settled_at",
    )
    assert pares == [
        datetime(2026, 5, 5, 15, 0),
        datetime(2026, 6, 20, 15, 0),
        datetime(2026, 8, 1, 1, 0),
    ], "cada linha antiga tem de ficar liquidada na SUA data, não numa data comum"


def test_settled_at_copia_transaction_date_linha_a_linha(banco_migrado):
    """Reforça o de cima pelo outro lado: nenhuma linha diverge da própria data.

    Um `SET settled_at = <constante>` passaria no teste anterior se as datas
    coincidissem por acaso; esta comparação é linha a linha, no banco.
    """
    engine, _ = banco_migrado
    with engine.connect() as conn:
        divergentes = conn.execute(sa.text(
            'SELECT COUNT(*) FROM "transaction" WHERE settled_at IS DISTINCT FROM transaction_date'
            if engine.dialect.name == "postgresql"
            else 'SELECT COUNT(*) FROM "transaction" WHERE settled_at IS NOT transaction_date'
        )).scalar_one()
    assert divergentes == 0


# ---------------------------------------------------------------------------
# Os defaults, que decidem de que lado o ADR se aplica

def test_espaco_existente_nasce_com_o_controle_ligado(banco_migrado):
    """LIGADO, e só é seguro porque o backfill acima já liquidou o histórico:
    o espaço passa a controlar pagamento sem que nada do passado entre na fila."""
    engine, _ = banco_migrado
    with engine.connect() as conn:
        valores = conn.execute(
            sa.text("SELECT settlement_tracking FROM workspace")
        ).scalars().all()
    assert valores == [True]


def test_recorrencia_existente_nasce_sem_debito_automatico(banco_migrado):
    """DESLIGADO: `auto_settle` afirma que o banco debita sozinho, e assumir isso
    para toda recorrência já cadastrada reintroduziria o defeito de origem
    justamente onde ele mais aparecia."""
    engine, _ = banco_migrado
    with engine.connect() as conn:
        valores = conn.execute(
            sa.text("SELECT auto_settle FROM recurringexpense")
        ).scalars().all()
    assert valores == [False]


# ---------------------------------------------------------------------------
# Repetibilidade e reversão

def test_o_indice_parcial_existe(banco_migrado):
    """Sem ele, Contas a pagar varre a tabela inteira de lançamentos."""
    engine, _ = banco_migrado
    indices = {i["name"] for i in sa.inspect(engine).get_indexes("transaction")}
    assert "ix_transaction_a_liquidar" in indices


def test_rodar_de_novo_nao_reescreve_pagamento_de_verdade(banco_migrado, url_descartavel):
    """O `WHERE settled_at IS NULL` é o que torna a migração repetível.

    Cenário: alguém já marcou uma conta como paga em outra data, e a migração roda
    de novo (redeploy, `downgrade`+`upgrade`). Sem a guarda, ela carimbaria a data
    do lançamento por cima e a saída trocaria de mês em silêncio.
    """
    engine, _ = banco_migrado
    with engine.begin() as conn:
        conn.execute(sa.text(
            'UPDATE "transaction" SET settled_at = :pago WHERE title = :t'
        ), {"pago": "2026-06-14 15:00:00", "t": "Mercado de maio"})

    _upgrade(url_descartavel, "head")

    assert _datas(
        engine,
        'SELECT settled_at FROM "transaction" WHERE title = :t',
        "settled_at",
        t="Mercado de maio",
    ) == [datetime(2026, 6, 14, 15, 0)]


def test_downgrade_e_upgrade_sobrevivem_a_um_banco_com_dados(banco_migrado, url_descartavel):
    """A volta tem de funcionar: é o caminho de um rollback de produção.

    Depois de descer e subir, o backfill roda de novo em cima das colunas
    recriadas — e o histórico volta a estar liquidado.
    """
    engine, _ = banco_migrado
    resultado = _alembic(url_descartavel, "downgrade", REVISAO_ANTERIOR)
    assert resultado.returncode == 0, f"{resultado.stdout}\n{resultado.stderr}"
    assert "settled_at" not in {
        c["name"] for c in sa.inspect(engine).get_columns("transaction")
    }

    _upgrade(url_descartavel, "head")
    assert None not in _datas(
        engine, 'SELECT settled_at FROM "transaction"', "settled_at"
    )
