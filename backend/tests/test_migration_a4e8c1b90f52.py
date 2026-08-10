"""A migração do ADR 0021 contra um banco LEGADO POVOADO, não vazio.

`alembic upgrade head` em banco limpo já rodava no CI e passava — e passava
justamente porque não havia dado nenhum para a migração maltratar. A auditoria
externa reproduziu num banco descartável o que o CI não via:

- a mesma pessoa com duas contas "Nubank" (uma por workspace, legítimo até aqui);
- um `transactionpayer` apontando para a segunda;
- depois do upgrade, só a primeira conta sobrevivia e o pagador seguia apontando
  para um id apagado.

No SQLite isso é referência órfã. No Postgres, onde `fk_transactionpayer_account`
é verificada na hora do `DELETE`, é a **migração abortando** — e como o Dockerfile
roda `alembic upgrade head` antes do uvicorn, é o container não subir.

O alembic é chamado por SUBPROCESSO de propósito: `alembic/env.py` sobrescreve
`sqlalchemy.url` com `settings.DATABASE_URL`, então injetar a URL por objeto de
config não funcionaria — e o subprocesso exercita exatamente a linha do
`Dockerfile`.

Roda em SQLite (padrão) e em Postgres, se `TEST_DATABASE_URL` apontar para lá: o
SQLite prova a integridade dos dados, o Postgres prova que a FK não estoura.
"""
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa

BACKEND_DIR = Path(__file__).resolve().parents[1]
REVISAO_ANTERIOR = "f3a7d21e08b4"
REVISAO = "a4e8c1b90f52"

AGORA = "2026-07-01 12:00:00"


def _alembic(url: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": url, "APP_ENV": "test"}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        # A saída tem acentos e o console do Windows não é UTF-8: sem isto o
        # decode do subprocess estoura antes de o teste chegar à asserção.
        encoding="utf-8",
        errors="replace",
    )


def _upgrade(url: str, revisao: str) -> None:
    resultado = _alembic(url, "upgrade", revisao)
    assert resultado.returncode == 0, (
        f"upgrade para {revisao} falhou:\n{resultado.stdout}\n{resultado.stderr}"
    )


@pytest.fixture(scope="module")
def url_descartavel(tmp_path_factory):
    """Banco vazio e exclusivo deste módulo.

    Em Postgres cria um database próprio: rodar num que já está na head não
    testaria nada, e o `TEST_DATABASE_URL` do CI aponta para um desses.
    """
    alvo = os.environ.get("TEST_DATABASE_URL", "")
    if not alvo.startswith("postgres"):
        arquivo = tmp_path_factory.mktemp("mig") / "legado.db"
        yield f"sqlite:///{arquivo.as_posix()}"
        return

    nome = f"mig_{uuid.uuid4().hex[:12]}"
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
    """Sobe em `f3`, semeia o legado, sobe para a head. Uma vez por módulo.

    Os cenários são linhas independentes, então cabem todos no mesmo banco — e o
    upgrade roda UMA vez, que é o caro aqui.

    `yield` + `dispose()`, não `return engine`: sem fechar o pool a conexão fica
    viva até o interpretador coletá-la, e a suíte terminava verde com
    `ResourceWarning: unclosed database`.
    """
    _upgrade(url_descartavel, REVISAO_ANTERIOR)
    engine = sa.create_engine(url_descartavel)
    with engine.begin() as conn:
        _semeia(conn)

    _upgrade(url_descartavel, REVISAO)
    yield engine
    engine.dispose()


def _semeia(conn) -> None:
    def exec_(sql: str, **params):
        return conn.execute(sa.text(sql), params or {})

    def ids(sql: str, **params) -> int:
        return exec_(sql + " RETURNING id", **params).scalar_one()

    campos_user = (
        "(name, email, is_active, password_hash, created_at, updated_at, "
        "needs_onboarding, report_currency)"
    )
    valores_user = (
        "(:nome, :email, TRUE, 'x', :agora, :agora, FALSE, 'BRL')"
    )
    alice = ids(
        f"INSERT INTO \"user\" {campos_user} VALUES {valores_user}",
        nome="Alice", email="alice@example.com", agora=AGORA,
    )
    bob = ids(
        f"INSERT INTO \"user\" {campos_user} VALUES {valores_user}",
        nome="Bob", email="bob@example.com", agora=AGORA,
    )

    def workspace(nome: str) -> int:
        return ids(
            "INSERT INTO workspace (name, created_at, updated_at, event_seq, base_currency)"
            " VALUES (:nome, :agora, :agora, 0, 'BRL')",
            nome=nome, agora=AGORA,
        )

    casa = workspace("Casa")
    viagem = workspace("Viagem")
    # Workspace SEM MEMBRO: é dele que sai o recurso sem dono possível.
    orfao = workspace("Abandonado")

    for ws, user, papel in ((casa, alice, "owner"), (casa, bob, "member"),
                            (viagem, alice, "owner")):
        exec_(
            "INSERT INTO workspacemembership"
            " (workspace_id, user_id, created_at, updated_at, role, financial_access)"
            " VALUES (:ws, :u, :agora, :agora, :papel, 'full_workspace')",
            ws=ws, u=user, papel=papel, agora=AGORA,
        )

    def conta(ws: int, nome: str, tipo: str = "checking", moeda: str = "BRL") -> int:
        return ids(
            "INSERT INTO paymentaccount"
            " (workspace_id, name, type, currency, active, created_at, updated_at)"
            " VALUES (:ws, :nome, :tipo, :moeda, TRUE, :agora, :agora)",
            ws=ws, nome=nome, tipo=tipo, moeda=moeda, agora=AGORA,
        )

    # CENÁRIO 1 — a mesma conta real, vista de dois workspaces. Idênticas em tipo
    # e moeda: têm de FUNDIR, com as referências reapontadas.
    conta(casa, "Nubank")
    nubank_viagem = conta(viagem, "Nubank")

    # CENÁRIO 2 — mesmo nome, moeda diferente: são contas DIFERENTES. Nenhuma
    # pode sumir; a segunda é renomeada.
    conta(casa, "Wise", moeda="BRL")
    conta(viagem, "Wise", moeda="USD")

    # CENÁRIO 2b — o desempate não pode colidir com um nome já cadastrado à mão.
    conta(casa, "Wise (2)", moeda="EUR")

    # CENÁRIO 3 — conta e cartão em workspace sem membro: sem dono possível.
    conta_orfa = conta(orfao, "Conta Fantasma")

    def cartao(ws: int, nome: str) -> int:
        return ids(
            "INSERT INTO creditcard"
            " (name, \"limit\", closing_day, due_day, currency, workspace_id,"
            "  created_at, updated_at)"
            " VALUES (:nome, 5000, 10, 20, 'BRL', :ws, :agora, :agora)",
            nome=nome, ws=ws, agora=AGORA,
        )

    cartao_alice = cartao(casa, "Cartão da Alice")
    cartao_orfao = cartao(orfao, "Cartão Fantasma")

    def fatura(card: int) -> int:
        return ids(
            "INSERT INTO cardstatement"
            " (month, closing_date, due_date, status, total_amount, card_id,"
            "  created_at, updated_at)"
            " VALUES ('2026-07', :fecha, :vence, 'open', 100, :card, :agora, :agora)",
            card=card, fecha="2026-07-10", vence="2026-07-20", agora=AGORA,
        )

    fatura_alice = fatura(cartao_alice)
    fatura_orfa = fatura(cartao_orfao)

    # O pagamento de fatura aponta para a SEGUNDA conta "Nubank" — é a referência
    # que a versão anterior da migração nunca limpava, nem antes nem depois.
    exec_(
        "INSERT INTO statementpayment"
        " (workspace_id, statement_id, account_id, amount, paid_at, created_at, updated_at)"
        " VALUES (:ws, :stmt, :conta, 100, :agora, :agora, :agora)",
        ws=casa, stmt=fatura_alice, conta=nubank_viagem, agora=AGORA,
    )
    # Pagamento pendurado no cartão sem dono: some junto com a fatura.
    exec_(
        "INSERT INTO statementpayment"
        " (workspace_id, statement_id, account_id, amount, paid_at, created_at, updated_at)"
        " VALUES (:ws, :stmt, :conta, 50, :agora, :agora, :agora)",
        ws=orfao, stmt=fatura_orfa, conta=conta_orfa, agora=AGORA,
    )

    def transacao(ws: int, titulo: str, card=None, stmt=None) -> int:
        return ids(
            "INSERT INTO \"transaction\""
            " (title, currency, total_amount, transaction_date, status, workspace_id,"
            "  created_at, updated_at, split_mode, credit_card_id, statement_id)"
            " VALUES (:titulo, 'BRL', 100, :agora, 'confirmed', :ws, :agora, :agora,"
            "         'transaction', :card, :stmt)",
            titulo=titulo, ws=ws, card=card, stmt=stmt, agora=AGORA,
        )

    tx_viagem = transacao(viagem, "Jantar")
    transacao(casa, "Compra no cartão fantasma", card=cartao_orfao, stmt=fatura_orfa)

    # O pagador que a auditoria reproduziu: aponta para a conta duplicada.
    exec_(
        "INSERT INTO transactionpayer"
        " (transaction_id, user_id, amount, created_at, updated_at, account_id)"
        " VALUES (:tx, :u, 100, :agora, :agora, :conta)",
        tx=tx_viagem, u=alice, agora=AGORA, conta=nubank_viagem,
    )
    assert bob  # membro sem papel `owner`: existe para o backfill ter de escolher


def _um(engine, sql: str, **params):
    with engine.connect() as conn:
        return conn.execute(sa.text(sql), params).first()


def _todos(engine, sql: str, **params):
    with engine.connect() as conn:
        return conn.execute(sa.text(sql), params).fetchall()


# ---------------------------------------------------------------------------
# Fusão: a mesma conta em dois workspaces vira uma, sem largar referência

def test_conta_duplicada_identica_funde_numa_so(banco_migrado):
    contas = _todos(
        banco_migrado,
        "SELECT id FROM paymentaccount WHERE name = 'Nubank'",
    )
    assert len(contas) == 1, "duas contas idênticas do mesmo dono deviam ter fundido"


def test_pagador_segue_a_conta_sobrevivente(banco_migrado):
    """O caso exato da auditoria: o pagador apontava para o id apagado."""
    linha = _um(
        banco_migrado,
        "SELECT p.account_id, c.name FROM transactionpayer p"
        " LEFT JOIN paymentaccount c ON c.id = p.account_id",
    )
    assert linha.account_id is not None, "a referência do pagador foi descartada"
    assert linha.name == "Nubank", "o pagador ficou apontando para outra conta"


def test_pagamento_de_fatura_segue_a_conta_sobrevivente(banco_migrado):
    """`statementpayment.account_id` nunca era limpo nem reapontado."""
    linha = _um(
        banco_migrado,
        "SELECT s.account_id, c.name FROM statementpayment s"
        " LEFT JOIN paymentaccount c ON c.id = s.account_id"
        " WHERE s.amount = 100",
    )
    assert linha is not None, "o pagamento da fatura viva sumiu"
    assert linha.name == "Nubank"


def test_nenhuma_referencia_de_conta_fica_orfa(banco_migrado):
    """Vale nos dois bancos: no Postgres a FK já teria estourado; no SQLite, que
    roda com FK desligada, a órfã só aparece numa checagem como esta."""
    for tabela in ("transactionpayer", "statementpayment"):
        orfas = _todos(
            banco_migrado,
            f"SELECT id FROM {tabela} WHERE account_id IS NOT NULL"
            " AND account_id NOT IN (SELECT id FROM paymentaccount)",
        )
        assert orfas == [], f"{tabela} ficou com referência para conta apagada"


# ---------------------------------------------------------------------------
# Renomeação: diferença material não é duplicata

def test_contas_diferentes_com_mesmo_nome_sobrevivem_renomeadas(banco_migrado):
    nomes = sorted(
        r.name for r in _todos(
            banco_migrado, "SELECT name FROM paymentaccount WHERE name LIKE 'Wise%'"
        )
    )
    assert len(nomes) == 3, f"alguma conta 'Wise' foi descartada: {nomes}"
    assert nomes == ["Wise", "Wise (2)", "Wise (3)"], (
        "o desempate colidiu com o nome que já existia"
    )


def test_moedas_das_contas_wise_intactas(banco_migrado):
    moedas = {
        r.name: r.currency for r in _todos(
            banco_migrado,
            "SELECT name, currency FROM paymentaccount WHERE name LIKE 'Wise%'",
        )
    }
    assert set(moedas.values()) == {"BRL", "USD", "EUR"}


# ---------------------------------------------------------------------------
# Sem dono possível: apaga soltando as referências ANTES

def test_recurso_de_workspace_sem_membro_some(banco_migrado):
    assert _um(
        banco_migrado, "SELECT id FROM paymentaccount WHERE name = 'Conta Fantasma'"
    ) is None
    assert _um(
        banco_migrado, "SELECT id FROM creditcard WHERE name = 'Cartão Fantasma'"
    ) is None


def test_lancamento_do_cartao_removido_perde_a_referencia_mas_sobrevive(banco_migrado):
    linha = _um(
        banco_migrado,
        "SELECT credit_card_id, statement_id FROM \"transaction\""
        " WHERE title = 'Compra no cartão fantasma'",
    )
    assert linha is not None, "o lançamento foi apagado junto com o cartão"
    assert linha.credit_card_id is None
    assert linha.statement_id is None


def test_fatura_e_pagamento_do_cartao_removido_somem(banco_migrado):
    assert _todos(
        banco_migrado,
        "SELECT id FROM cardstatement WHERE card_id NOT IN (SELECT id FROM creditcard)",
    ) == []
    assert _todos(
        banco_migrado,
        "SELECT id FROM statementpayment"
        " WHERE statement_id NOT IN (SELECT id FROM cardstatement)",
    ) == []


def test_dono_herdado_do_workspace(banco_migrado):
    """`owner` do workspace vira dono; o cartão da Casa é da Alice, não do Bob."""
    linha = _um(
        banco_migrado,
        "SELECT u.email FROM creditcard c JOIN \"user\" u ON u.id = c.owner_user_id"
        " WHERE c.name = 'Cartão da Alice'",
    )
    assert linha.email == "alice@example.com"


# ---------------------------------------------------------------------------
# Rollback

def test_downgrade_recusa_em_vez_de_fingir(banco_migrado, url_descartavel):
    """A versão anterior recriava o schema sem o dado e marcava `f3` como
    aplicada — rollback que reporta sucesso e entrega um banco que não opera."""
    resultado = _alembic(url_descartavel, "downgrade", "-1")
    saida = resultado.stdout + resultado.stderr
    assert resultado.returncode != 0, "o downgrade fingiu que deu certo"
    # Asserção em texto ASCII de propósito: o processo filho escreve o traceback
    # no encoding do console (cp1252 no Windows) e os acentos chegam mutilados.
    assert "RuntimeError" in saida
    assert "docs/runbook-deploy.md" in saida, "a recusa não aponta o caminho de volta"


def test_banco_continua_na_head_depois_da_recusa(banco_migrado, url_descartavel):
    resultado = _alembic(url_descartavel, "current")
    assert REVISAO in resultado.stdout
