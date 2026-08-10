"""A migração de datas civis (ADR 0025) contra um banco POVOADO, não vazio.

`alembic upgrade head` em banco limpo passava no CI — e passava porque não havia
linha nenhuma para a migração ler. Com dados, dois defeitos apareciam:

1. **Ela quebrava no SQLite.** As linhas eram lidas por `sa.text()` sem tipo
   declarado, e sem tipo o SQLAlchemy não aplica processador de resultado: a
   coluna DATETIME volta como `str` do driver. O `.time()` seguinte estourava
   `AttributeError: 'str' object has no attribute 'time'`, e como o Dockerfile
   roda `alembic upgrade head` antes do uvicorn, é o container não subir.

2. **No Postgres ela convertia pela metade.** A barreira contra colisão era um
   conjunto de INSTANTES global por chamada, sem olhar a que recorrência a linha
   pertencia. A primeira despesa do dia 1º reancorava e ocupava `12:00 local`;
   toda outra linha daquele mesmo dia — de outras recorrências, sem relação
   nenhuma — era pulada e ficava na meia-noite, isto é, com o bug que a migração
   existe para corrigir.

A unicidade real é `(recorrência, ocorrência)`, e só a tabela `income` tem um
índice único que envolva a coluna movida. Este módulo fixa as duas coisas.

Alembic por SUBPROCESSO e fixture de banco descartável pelos mesmos motivos de
`test_migration_a4e8c1b90f52.py` — ver o cabeçalho de lá.
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
REVISAO_ANTERIOR = "b6d4f0a72e91"

AGORA = "2026-07-01 12:00:00"
# América/São Paulo é UTC−3 o ano todo desde 2019: meio-dia local = 15:00 UTC.
# Cravado como literal de propósito — derivar o esperado com `civil_instant`
# faria o teste concordar com a migração por construção, inclusive se as duas
# estivessem erradas juntas.
MEIO_DIA_UTC = datetime(2026, 8, 1, 15, 0)
MEIA_NOITE = "2026-08-01 00:00:00"
# Instante de VERDADE (uma compra às 22h). A migração não pode tocá-lo.
INSTANTE_REAL = "2026-08-01 22:30:00"


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
        arquivo = tmp_path_factory.mktemp("mig_datas") / "civil.db"
        yield f"sqlite:///{arquivo.as_posix()}"
        return

    nome = f"migdt_{uuid.uuid4().hex[:12]}"
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
    """Sobe na revisão anterior, semeia à meia-noite, e sobe até a head.

    Até a HEAD, e não só até `c7e3b81f04a9`: com dados no banco, o que importa é
    a cadeia inteira sobreviver — é isso que o `alembic upgrade head` do
    Dockerfile faz em produção.
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
        " VALUES ('Dona', 'datas@example.com', TRUE, 'x', :agora, :agora, FALSE, 'BRL')",
        agora=AGORA,
    )
    ws = ids(
        "INSERT INTO workspace (name, created_at, updated_at, event_seq, base_currency)"
        " VALUES ('Casa', :agora, :agora, 0, 'BRL')",
        agora=AGORA,
    )

    def recorrencia(titulo: str) -> int:
        return ids(
            "INSERT INTO recurringexpense"
            " (title, base_amount, frequency, \"interval\", day_of_month, is_active,"
            "  workspace_id, created_by_user_id, currency, created_at, updated_at)"
            " VALUES (:t, 100, 'monthly', 1, 1, TRUE, :ws, :u, 'BRL', :agora, :agora)",
            t=titulo, ws=ws, u=user, agora=AGORA,
        )

    def despesa(titulo: str, quando: str, rec: int = None) -> int:
        return ids(
            'INSERT INTO "transaction"'
            " (title, currency, total_amount, transaction_date, status, workspace_id,"
            "  created_at, updated_at, split_mode, recurring_expense_id, billing_month)"
            " VALUES (:t, 'BRL', 100, :quando, 'confirmed', :ws, :agora, :agora,"
            "         'transaction', :rec, '2026-08')",
            t=titulo, quando=quando, ws=ws, rec=rec, agora=AGORA,
        )

    # CENÁRIO 1 — duas recorrências DIFERENTES, ocorrência no MESMO dia, ambas à
    # meia-noite. É o caso que a barreira global estragava: a segunda ficava para
    # trás por "colidir" com um instante que não é vaga dela.
    despesa("Aluguel", MEIA_NOITE, recorrencia("Aluguel"))
    despesa("Internet", MEIA_NOITE, recorrencia("Internet"))

    # CENÁRIO 2 — despesa avulsa (sem recorrência) à meia-noite: NÃO é população
    # desta migração e tem de ficar onde está.
    despesa("Avulsa", MEIA_NOITE)

    # CENÁRIO 3 — instante de verdade numa linha de recorrência: hora ≠ 00:00,
    # não se toca.
    despesa("Assinatura noturna", INSTANTE_REAL, recorrencia("Assinatura"))

    def renda_recorrente(titulo: str) -> int:
        return ids(
            "INSERT INTO recurringincome"
            " (title, base_amount, currency, frequency, \"interval\", day_of_month,"
            "  is_active, user_id, created_at, updated_at)"
            " VALUES (:t, 5000, 'BRL', 'monthly', 1, 1, TRUE, :u, :agora, :agora)",
            t=titulo, u=user, agora=AGORA,
        )

    def renda(titulo: str, quando: str, rec: int = None) -> int:
        return ids(
            "INSERT INTO income"
            " (title, amount, currency, received_at, user_id, recurring_income_id,"
            "  billing_month, created_at, updated_at)"
            " VALUES (:t, 5000, 'BRL', :quando, :u, :rec, '2026-08', :agora, :agora)",
            t=titulo, quando=quando, u=user, rec=rec, agora=AGORA,
        )

    # CENÁRIO 4 — duas rendas de recorrências DIFERENTES no mesmo dia: as duas
    # migram (vagas distintas na `uq_recurring_income_occurrence`).
    renda("Salário", MEIA_NOITE, renda_recorrente("Salário"))
    renda("Aluguel recebido", MEIA_NOITE, renda_recorrente("Aluguel recebido"))

    # CENÁRIO 5 — a colisão que de fato existe. Duas linhas da MESMA recorrência
    # à meia-noite são impossíveis: `uq_recurring_income_occurrence` já as
    # proíbe. O estado real é MISTO — a aplicação nova (que grava ao meio-dia)
    # rodou antes da migração, não encontrou a linha antiga no dedup por data, e
    # criou uma segunda para a mesma ocorrência. Reancorar a velha por cima da
    # nova violaria a unique e derrubaria o `alembic upgrade` inteiro.
    gemea = renda_recorrente("Bico")
    renda("Bico velha", MEIA_NOITE, gemea)
    renda("Bico nova", "2026-08-01 15:00:00", gemea)

    # CENÁRIO 6 — linha de lote de import (ADR 0008), sem índice único nenhum.
    lote = ids(
        "INSERT INTO importbatch"
        " (workspace_id, filename, created_by_user_id, total_rows, imported_count,"
        "  ignored_count, duplicate_count, skipped_count, created_at)"
        " VALUES (:ws, 'extrato.csv', :u, 2, 2, 0, 0, 0, :agora)",
        ws=ws, u=user, agora=AGORA,
    )
    for i, titulo in enumerate(("Padaria", "Farmácia"), start=1):
        exec_(
            "INSERT INTO importrow"
            " (batch_id, workspace_id, line, title, amount, transaction_date,"
            "  fingerprint, status, created_at)"
            " VALUES (:lote, :ws, :linha, :t, 50, :quando, :fp, 'imported', :agora)",
            lote=lote, ws=ws, linha=i, t=titulo, quando=MEIA_NOITE,
            fp=f"fp-{i}", agora=AGORA,
        )


def _datas(engine, sql: str, coluna: str, **params) -> list[datetime]:
    """Lê uma coluna de data DECLARANDO o tipo.

    O `.columns()` aqui não é cerimônia: é a mesma armadilha que o defeito 1
    documenta, do lado do teste. Sem tipo, o driver do SQLite devolve `str` e as
    asserções comparariam `'2026-08-01 15:00:00.000000'` com um `datetime` —
    falhando em todo cenário, inclusive nos que a migração acertou.
    """
    with engine.connect() as conn:
        linhas = conn.execute(
            sa.text(sql).columns(sa.column(coluna, sa.DateTime())), params
        ).fetchall()
    return [linha[0] for linha in linhas]


def _todos(engine, sql: str, **params):
    with engine.connect() as conn:
        return conn.execute(sa.text(sql), params).fetchall()


def _quando(engine, tabela: str, coluna: str, titulo: str) -> datetime:
    valores = _datas(
        engine,
        f'SELECT {coluna} FROM "{tabela}" WHERE title = :t',
        coluna,
        t=titulo,
    )
    assert len(valores) == 1, f"{titulo} não é uma linha só"
    return valores[0]


# ---------------------------------------------------------------------------
# O defeito 1: a migração nem chegava a rodar

def test_a_migracao_sobrevive_a_um_banco_com_dados(banco_migrado):
    """No SQLite, `sa.text()` devolvia `str` e o `.time()` estourava. O
    `_upgrade` da fixture já teria falhado — este teste nomeia o porquê."""
    _, resultado = banco_migrado
    assert "AttributeError" not in (resultado.stdout + resultado.stderr)


# ---------------------------------------------------------------------------
# O defeito 2: a barreira global bloqueava linhas de outra recorrência

def test_recorrencias_diferentes_no_mesmo_dia_migram_as_duas(banco_migrado):
    """O achado da auditoria: a segunda despesa do dia ficava na meia-noite."""
    engine, _ = banco_migrado
    assert _quando(engine, "transaction", "transaction_date", "Aluguel") == MEIO_DIA_UTC
    assert _quando(engine, "transaction", "transaction_date", "Internet") == MEIO_DIA_UTC


def test_rendas_de_recorrencias_diferentes_no_mesmo_dia_migram_as_duas(banco_migrado):
    engine, _ = banco_migrado
    assert _quando(engine, "income", "received_at", "Salário") == MEIO_DIA_UTC
    assert _quando(engine, "income", "received_at", "Aluguel recebido") == MEIO_DIA_UTC


def test_colisao_real_na_mesma_recorrencia_e_pulada_sem_estourar(banco_migrado):
    """A barreira continua existindo onde ela de fato protege.

    A linha nova já ocupa o meio-dia; a velha não pode ser reancorada por cima —
    seria `IntegrityError` e o upgrade inteiro abortaria. Ela fica onde está, e a
    migração imprime o que pulou.
    """
    engine, resultado = banco_migrado
    assert _quando(engine, "income", "received_at", "Bico nova") == MEIO_DIA_UTC
    assert _quando(engine, "income", "received_at", "Bico velha") == datetime(
        2026, 8, 1, 0, 0
    ), "reancorar por cima da linha nova violaria a unique"
    # Asserção em ASCII de propósito, como no módulo irmão: o processo filho
    # escreve no encoding do console (cp1252 no Windows) e os acentos chegam
    # mutilados — "não" vira "n�o" e a comparação falha por um detalhe que
    # não é o assunto do teste.
    assert "[c7e3b81f04a9] income#" in resultado.stdout, (
        "o que a migração deixa para trás tem de sair na saída, não sumir calado"
    )


# ---------------------------------------------------------------------------
# Quem não é população da migração

def test_despesa_avulsa_nao_e_tocada(banco_migrado):
    """Sem `recurring_expense_id` e sem linha de import, não é data civil."""
    engine, _ = banco_migrado
    assert _quando(engine, "transaction", "transaction_date", "Avulsa") == datetime(
        2026, 8, 1, 0, 0
    )


def test_instante_de_verdade_nao_e_tocado(banco_migrado):
    """Hora ≠ 00:00 carrega informação: mover seria destruí-la."""
    engine, _ = banco_migrado
    assert _quando(
        engine, "transaction", "transaction_date", "Assinatura noturna"
    ) == datetime(2026, 8, 1, 22, 30)


# ---------------------------------------------------------------------------
# A linha do lote, que não tem índice único nenhum

def test_todas_as_linhas_de_import_migram(banco_migrado):
    """Sem unique na tabela, barreira nenhuma pode segurar a segunda linha."""
    engine, _ = banco_migrado
    horarios = _datas(
        engine,
        "SELECT transaction_date FROM importrow ORDER BY line",
        "transaction_date",
    )
    assert horarios == [MEIO_DIA_UTC, MEIO_DIA_UTC]
