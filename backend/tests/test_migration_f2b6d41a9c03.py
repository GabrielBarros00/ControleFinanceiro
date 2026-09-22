"""A migração da quitação em lote (ADR 0023) contra um banco POVOADO.

`alembic upgrade head` em banco vazio adiciona a coluna e não prova nada: o que
esta revisão promete é o **backfill**. Quem já usou `settle-past` tem, gravado,
um caixa inflado — uma saída retroativa em cada mês em que uma parcela do
contrato antigo venceu. A coluna nascer `false` deixaria esse passado errado
intacto, e o conserto valeria só para quem ainda não usou a rota.

O backfill não tem uma marca explícita para seguir (a rota antiga não deixava
nenhuma), então ele reconhece a quitação em lote pela ASSINATURA que só ela
produz: `paid_at` na meia-noite exata do vencimento — o pagamento individual
grava `datetime.now(UTC)`, e o frontend nunca envia `paid_at` —, sem conta
declarada e sem despesa vinculada viva.

Cada um desses três termos é um falso positivo evitado, e por isso cada um tem
aqui o seu caso de controle: marcar de menos deixa o caixa inflado, marcar de
mais **apaga do extrato uma saída que aconteceu de verdade**. Os dois erros são
silenciosos, e é por isso que o teste semeia os cinco casos e não só o feliz.

Alembic por SUBPROCESSO e fixture de banco descartável pelos mesmos motivos de
`test_migration_c7e3b81f04a9.py` — ver o cabeçalho de lá.
"""
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa

BACKEND_DIR = Path(__file__).resolve().parents[1]
REVISAO_ANTERIOR = "d5a9e3c721b4"

AGORA = "2026-07-01 12:00:00"
#: O carimbo da quitação em lote: `paid_at = due_date`, que no banco é a meia-noite.
VENCEU_E_QUITADO = "2026-08-12 00:00:00"
VENCIMENTO = "2026-08-12"
#: O carimbo do pagamento individual: um instante qualquer do dia.
PAGOU_DE_VERDADE = "2026-08-12 14:33:21"


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
        arquivo = tmp_path_factory.mktemp("mig_lote") / "quitacao.db"
        yield f"sqlite:///{arquivo.as_posix()}"
        return

    nome = f"miglote_{uuid.uuid4().hex[:12]}"
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
    """Sobe na revisão anterior, semeia as cinco parcelas, e sobe até a head."""
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
        " VALUES ('Dona', 'quitacao@example.com', TRUE, 'x', :agora, :agora, FALSE, 'BRL')",
        agora=AGORA,
    )
    ws = ids(
        "INSERT INTO workspace (name, created_at, updated_at, event_seq, base_currency)"
        " VALUES ('Casa', :agora, :agora, 0, 'BRL')",
        agora=AGORA,
    )
    conta = ids(
        "INSERT INTO paymentaccount"
        " (name, type, currency, active, owner_user_id, is_default, created_at, updated_at)"
        " VALUES ('Corrente', 'checking', 'BRL', TRUE, :u, FALSE, :agora, :agora)",
        u=user, agora=AGORA,
    )
    financiamento = ids(
        "INSERT INTO financing"
        " (title, total_amount, interest_rate, start_date, installments_count, method,"
        "  status, currency, owner_user_id, created_at, updated_at)"
        " VALUES ('Apartamento', 300000, 0.008, '2026-01-10', 5, 'SAC', 'active', 'BRL',"
        "         :u, :agora, :agora)",
        u=user, agora=AGORA,
    )

    def parcela(numero: int, **campos) -> int:
        colunas = {
            "financing_id": financiamento,
            "installment_number": numero,
            "due_date": VENCIMENTO,
            "principal_amount": 1000,
            "interest_amount": 0,
            "total_amount": 1000,
            "remaining_balance": 0,
            "is_paid": True,
            **campos,
        }
        nomes = ", ".join(colunas)
        marcas = ", ".join(f":{c}" for c in colunas)
        return ids(
            f"INSERT INTO amortizationinstallment ({nomes}) VALUES ({marcas})",
            **colunas,
        )

    # 1) Quitada em lote: a assinatura completa. É a única que deve ser marcada.
    parcela(1, paid_at=VENCEU_E_QUITADO)
    # 2) Paga pelo app, sem despesa: o caixa tem nela a ÚNICA testemunha de que o
    #    dinheiro saiu. Marcá-la apagaria uma saída real do extrato.
    parcela(2, paid_at=PAGOU_DE_VERDADE)
    # 3) Meia-noite exata, MAS com despesa viva vinculada — pagamento declarado num
    #    espaço. Quem conta é a despesa; a parcela não é "de fora do app".
    com_despesa = parcela(3, paid_at=VENCEU_E_QUITADO)
    exec_(
        'INSERT INTO "transaction"'
        " (title, currency, total_amount, transaction_date, status, workspace_id,"
        "  created_at, updated_at, split_mode, billing_month, financing_installment_id)"
        " VALUES ('Parcela 3', 'BRL', 1000, :quando, 'confirmed', :ws, :agora, :agora,"
        "         'transaction', '2026-08', :parcela)",
        quando=VENCEU_E_QUITADO, ws=ws, agora=AGORA, parcela=com_despesa,
    )
    # 4) Meia-noite exata, MAS com conta declarada: a rota em lote não recebe conta,
    #    então isto foi alguém dizendo de onde o dinheiro saiu.
    parcela(4, paid_at=VENCEU_E_QUITADO, account_id=conta)
    # 5) Em aberto: não é paga de jeito nenhum.
    parcela(5, due_date="2026-10-12", is_paid=False, paid_at=None)


def _marcadas(engine) -> dict:
    with engine.connect() as conn:
        linhas = conn.execute(sa.text(
            "SELECT installment_number, paid_outside_app FROM amortizationinstallment"
            " ORDER BY installment_number"
        )).fetchall()
    return {numero: bool(marcado) for numero, marcado in linhas}


# ---------------------------------------------------------------------------
# A promessa: o caixa retroativo some, e só ele

def test_a_quitada_em_lote_deixa_de_ser_caixa(banco_migrado):
    """O ponto da migração: sem ele, o caixa já inflado continua inflado."""
    engine, _ = banco_migrado
    assert _marcadas(engine)[1] is True, (
        "a parcela com a assinatura da quitação em lote não foi marcada — o "
        "extrato de quem já usou a rota continua com saídas que nunca existiram"
    )


def test_a_paga_de_verdade_continua_no_caixa(banco_migrado):
    """O controle que importa: marcar de mais APAGA uma saída real do extrato."""
    engine, _ = banco_migrado
    assert _marcadas(engine)[2] is False, (
        "a parcela paga pelo app foi marcada como pagamento de fora — o caixa "
        "perdeu uma saída que aconteceu de verdade"
    )


def test_a_que_tem_despesa_vinculada_nao_e_marcada(banco_migrado):
    """Quem conta é a despesa. Marcar a parcela aqui esconderia a saída no dia
    em que a despesa fosse cancelada — ela deve voltar a contar sozinha."""
    engine, _ = banco_migrado
    assert _marcadas(engine)[3] is False


def test_a_que_tem_conta_declarada_nao_e_marcada(banco_migrado):
    """`settle-past` não recebe conta: se há uma, alguém declarou o pagamento."""
    engine, _ = banco_migrado
    assert _marcadas(engine)[4] is False


def test_a_em_aberto_nasce_falsa(banco_migrado):
    engine, _ = banco_migrado
    assert _marcadas(engine)[5] is False


# ---------------------------------------------------------------------------
# Repetibilidade e reversão

def test_rodar_de_novo_nao_desmarca_nem_remarca(banco_migrado, url_descartavel):
    """Redeploy roda a migração outra vez. O backfill filtra por
    `paid_outside_app = false`, então ele nunca desfaz o que já marcou — e não
    alcança uma parcela que o usuário tenha estornado e pago de verdade depois.
    """
    engine, _ = banco_migrado
    antes = _marcadas(engine)

    _upgrade(url_descartavel, "head")

    assert _marcadas(engine) == antes


def test_downgrade_e_upgrade_sobrevivem_a_um_banco_com_dados(banco_migrado, url_descartavel):
    """A volta é o caminho de um rollback de produção: a coluna some e, na
    subida seguinte, o backfill reencontra as mesmas parcelas."""
    engine, _ = banco_migrado
    resultado = _alembic(url_descartavel, "downgrade", REVISAO_ANTERIOR)
    assert resultado.returncode == 0, f"{resultado.stdout}\n{resultado.stderr}"
    assert "paid_outside_app" not in {
        c["name"] for c in sa.inspect(engine).get_columns("amortizationinstallment")
    }

    _upgrade(url_descartavel, "head")
    assert _marcadas(engine) == {1: True, 2: False, 3: False, 4: False, 5: False}
