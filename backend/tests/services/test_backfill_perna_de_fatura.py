"""O backfill supervisionado da perna de fatura (scripts/backfill_statement_amounts.py).

A migração `d8f1a37c025b` preenche `statement_amount` por IDENTIDADE e deixa de
fora as compras num cartão de moeda diferente. Este script as converte com a taxa
histórica, e uma auditoria achou dois defeitos nele — os dois com dinheiro no fim:

1. **IOF aplicado sempre.** Ele reimplementava taxa × (1 + IOF) por conta própria.
   Numa compra JÁ na moeda do cartão (US$ 20 num cartão USD, cuja perna contábil
   está em BRL só porque o workspace é BRL) não houve conversão nenhuma — e ela
   ganhava 3,5% do nada. A regra correta já existia em
   `compute_statement_conversion`; duas cópias divergiram, como sempre divergem.

2. **Fatura fechada seguia com o total errado.** O script só tocava a transação.
   Fechada ou paga, o sistema usa o `total_amount` CONGELADO
   (`CreditCardService.effective_total`), então o backfill apagava o aviso de
   linha incompatível e mantinha o total errado — pior que antes, porque agora
   invisível.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlmodel import Session, select

from app.domain.dates import civil_instant
from app.models.credit_card import (
    CardStatement,
    CreditCard,
    StatementPayment,
    StatementStatus,
)
from app.models.exchange_rate import ExchangeRate
from app.models.transaction import Transaction, TransactionStatus
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.services.credit_card_service import CreditCardService

from scripts.backfill_statement_amounts import backfill

DIA = date(2026, 8, 10)
QUANDO = civil_instant(DIA)
TAXA_USD = Decimal("5.000000")


@pytest.fixture(name="cena")
def cena_fixture(db_session: Session):
    """Workspace em BRL, cartão em USD — o par que a identidade não resolve."""
    user = User(name="Dona", email="backfill@t.com", password_hash="h", report_currency="USD")
    db_session.add(user)
    ws = Workspace(name="Casa", base_currency="BRL")
    db_session.add(ws)
    db_session.flush()
    db_session.add(
        WorkspaceMembership(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.owner)
    )
    card = CreditCard(
        name="Cartão gringo", limit=Decimal("10000.00"), closing_day=20, due_day=28,
        currency="USD", owner_user_id=user.id,
    )
    db_session.add(card)
    db_session.add_all([
        ExchangeRate(currency="USD", rate_date=DIA, rate=TAXA_USD, source="ptax"),
        ExchangeRate(currency="BRL", rate_date=DIA, rate=Decimal("1.000000"), source="base"),
    ])
    db_session.commit()
    db_session.refresh(card)
    return {"ws": ws, "user": user, "card": card}


def _compra_legada(db_session, cena, *, total, currency, original=None, original_currency=None):
    """Uma linha como a migração de identidade a deixou: perna de fatura = perna
    contábil, na moeda do WORKSPACE, divergindo da moeda do cartão."""
    statement = CreditCardService.get_or_create_statement(db_session, cena["card"], QUANDO)
    tx = Transaction(
        title="Compra antiga", total_amount=total, currency=currency,
        transaction_date=QUANDO, billing_month="2026-08",
        workspace_id=cena["ws"].id, created_by_user_id=cena["user"].id,
        status=TransactionStatus.confirmed,
        credit_card_id=cena["card"].id, statement_id=statement.id,
        original_amount=original, original_currency=original_currency,
    )
    db_session.add(tx)
    db_session.commit()
    db_session.refresh(tx)
    # A identidade da migração: statement_* copiados da perna contábil.
    tx.statement_amount = total
    tx.statement_currency = currency
    tx.statement_exchange_rate = Decimal("1")
    db_session.add(tx)
    db_session.commit()
    return tx, statement


# ---------------------------------------------------------------------------
# Defeito 1 — o IOF que não existia

def test_compra_ja_na_moeda_do_cartao_nao_ganha_iof(db_session, cena):
    """US$ 20 comprados num cartão USD continuam US$ 20 — não US$ 20,70.

    A perna contábil está em BRL (R$ 103,50, com o IOF do critério dela), e é
    isso que faz a linha entrar no recorte do backfill. Mas o banco não converteu
    nada nesta compra: origem e destino são a mesma moeda.
    """
    tx, _ = _compra_legada(
        db_session, cena,
        total=Decimal("103.50"), currency="BRL",
        original=Decimal("20.00"), original_currency="USD",
    )

    assert backfill(db_session, apply=True) == 0

    db_session.refresh(tx)
    assert tx.statement_currency == "USD"
    assert tx.statement_amount == Decimal("20.00"), "sem conversão, sem IOF"
    assert tx.statement_exchange_rate == Decimal("1")


def test_compra_em_moeda_diferente_converte_com_iof(db_session, cena):
    """O caso que o backfill existe para resolver: R$ 100 num cartão USD."""
    tx, _ = _compra_legada(db_session, cena, total=Decimal("100.00"), currency="BRL")

    assert backfill(db_session, apply=True) == 0

    db_session.refresh(tx)
    assert tx.statement_currency == "USD"
    # R$ 100 ÷ 5,00 = US$ 20, × 1,035 de IOF = US$ 20,70.
    assert tx.statement_amount == Decimal("20.70")


# ---------------------------------------------------------------------------
# Defeito 2 — o total congelado da fatura fechada

def test_fatura_fechada_tem_o_total_congelado_corrigido(db_session, cena):
    """O achado: a linha entrava no total calculado, mas a fechada não usa ele."""
    tx, statement = _compra_legada(db_session, cena, total=Decimal("100.00"), currency="BRL")
    # Fechada com o zero que a versão anterior do sistema congelou (a compra em
    # BRL não casava com o filtro de moeda, então a soma dava 0,00).
    statement.status = StatementStatus.closed
    statement.total_amount = Decimal("0.00")
    db_session.add(statement)
    db_session.commit()

    assert backfill(db_session, apply=True) == 0

    db_session.refresh(statement)
    assert statement.total_amount == Decimal("20.70"), (
        "o congelado é o que a fatura fechada mostra — corrigir só a transação "
        "apagaria o aviso e manteria o erro"
    )
    assert CreditCardService.effective_total(db_session, statement) == Decimal("20.70")


def test_fatura_aberta_nao_precisa_de_congelamento(db_session, cena):
    """Aberta soma na leitura: regravar `total_amount` seria ruído."""
    _, statement = _compra_legada(db_session, cena, total=Decimal("100.00"), currency="BRL")
    assert statement.status == StatementStatus.open
    antes = statement.total_amount

    assert backfill(db_session, apply=True) == 0

    db_session.refresh(statement)
    assert statement.total_amount == antes
    assert CreditCardService.effective_total(db_session, statement) == Decimal("20.70")


def test_fatura_que_vira_subpaga_e_anunciada(db_session, cena, capsys):
    """Regravar o total pode revelar que a fatura foi paga a menos.

    O script não mexe em status nem cria pagamento — cobrar a diferença é decisão
    humana. O que ele não pode é deixar isso passar em silêncio.
    """
    _, statement = _compra_legada(db_session, cena, total=Decimal("100.00"), currency="BRL")
    statement.status = StatementStatus.paid
    statement.total_amount = Decimal("0.00")
    db_session.add(statement)
    db_session.flush()
    db_session.add(StatementPayment(
        workspace_id=cena["ws"].id, statement_id=statement.id,
        amount=Decimal("5.00"), paid_at=QUANDO,
    ))
    db_session.commit()

    assert backfill(db_session, apply=True) == 0

    saida = capsys.readouterr().out
    assert "SUB-PAGAS" in saida
    db_session.refresh(statement)
    assert statement.total_amount == Decimal("20.70")
    assert statement.status == StatementStatus.paid, "o status é decisão humana"
    assert CreditCardService.statement_balance(db_session, statement) == Decimal("15.70")


# ---------------------------------------------------------------------------
# Dry-run

def test_dry_run_preve_o_congelado_sem_gravar_nada(db_session, cena, capsys):
    """A previsão tem de valer para a fatura FECHADA também.

    É o motivo de o dry-run gravar em memória e desfazer no fim em vez de nunca
    gravar: `compute_statement_total` soma em SQL, e com as linhas ainda na moeda
    velha o filtro de moeda as descartaria — o dry-run anunciaria um total que a
    rodada real não produziria.
    """
    tx, statement = _compra_legada(db_session, cena, total=Decimal("100.00"), currency="BRL")
    statement.status = StatementStatus.closed
    statement.total_amount = Decimal("0.00")
    db_session.add(statement)
    db_session.commit()

    assert backfill(db_session, apply=False) == 0

    saida = capsys.readouterr().out
    assert "20.70" in saida, "o dry-run tem de prever o valor real"
    assert "Dry-run" in saida

    db_session.expire_all()
    tx = db_session.exec(select(Transaction)).one()
    statement = db_session.exec(select(CardStatement)).one()
    assert tx.statement_amount == Decimal("100.00"), "nada pode ter sido gravado"
    assert tx.statement_currency == "BRL"
    assert statement.total_amount == Decimal("0.00")


def test_sem_cotacao_nao_grava_nada_e_sai_com_erro(db_session, cena, capsys):
    """`allow_fetch=False`: falta cotação, o operador roda `backfill_rates.py`."""
    outro_dia = civil_instant(date(2026, 3, 3))
    statement = CreditCardService.get_or_create_statement(db_session, cena["card"], outro_dia)
    tx = Transaction(
        title="Compra sem taxa", total_amount=Decimal("100.00"), currency="BRL",
        transaction_date=outro_dia, billing_month="2026-03",
        workspace_id=cena["ws"].id, created_by_user_id=cena["user"].id,
        status=TransactionStatus.confirmed,
        credit_card_id=cena["card"].id, statement_id=statement.id,
    )
    db_session.add(tx)
    db_session.commit()
    db_session.refresh(tx)
    tx.statement_amount = Decimal("100.00")
    tx.statement_currency = "BRL"
    db_session.add(tx)
    db_session.commit()

    assert backfill(db_session, apply=True) == 1, "falta de cotação tem de falhar alto"
    assert "Nada foi gravado" in capsys.readouterr().out

    db_session.expire_all()
    tx = db_session.exec(select(Transaction)).one()
    assert tx.statement_currency == "BRL", "a linha continua como estava"
