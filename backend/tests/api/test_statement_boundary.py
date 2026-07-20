"""Borda de fechamento da fatura: dia exato do fechamento, virada de ano e
posição do vencimento. Roteamento é server-side (CreditCardService)."""
from datetime import datetime
from decimal import Decimal

import pytest
from sqlmodel import Session

from app.models.credit_card import CreditCard
from app.services.credit_card_service import CreditCardService


@pytest.fixture(name="card")
def card_fixture(db_session: Session, seed_ws):
    card = CreditCard(
        workspace_id=seed_ws["ws"].id, name="Card",
        limit=Decimal("5000.00"), closing_day=25, due_day=5,
    )
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


def _month(db_session, card, iso):
    stmt = CreditCardService.get_or_create_statement(db_session, card, datetime.fromisoformat(iso))
    return stmt.month


def test_dia_anterior_ao_fechamento_fica_no_mes(db_session, card):
    # dia 24 < fechamento 25 → fatura do mês corrente
    assert _month(db_session, card, "2026-03-24T23:59:59") == "2026-03"


def test_dia_do_fechamento_vai_para_o_proximo(db_session, card):
    # dia 25 >= fechamento 25 → fatura do mês seguinte
    assert _month(db_session, card, "2026-03-25T00:00:00") == "2026-04"


def test_virada_de_ano(db_session, card):
    # dezembro, dia >= fechamento → janeiro do ano seguinte
    assert _month(db_session, card, "2026-12-27T10:00:00") == "2027-01"


def test_due_date_no_mes_seguinte_quando_vence_antes_de_fechar(db_session, card):
    # due_day 5 < closing_day 25 → vencimento cai no mês seguinte ao da fatura
    stmt = CreditCardService.get_or_create_statement(
        db_session, card, datetime.fromisoformat("2026-03-10T12:00:00")
    )
    assert stmt.month == "2026-03"
    assert stmt.closing_date.month == 3
    assert stmt.due_date.month == 4


def test_due_date_no_mesmo_mes_quando_vence_depois_de_fechar(db_session, seed_ws):
    card = CreditCard(
        workspace_id=seed_ws["ws"].id, name="Card2",
        limit=Decimal("5000.00"), closing_day=5, due_day=20,
    )
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    # due_day 20 > closing_day 5 → vencimento no mesmo mês da fatura
    stmt = CreditCardService.get_or_create_statement(
        db_session, card, datetime.fromisoformat("2026-03-02T12:00:00")
    )
    assert stmt.month == "2026-03"
    assert stmt.closing_date.month == 3
    assert stmt.due_date.month == 3


def test_dia_31_limitado_em_fevereiro(db_session, seed_ws):
    card = CreditCard(
        workspace_id=seed_ws["ws"].id, name="Card31",
        limit=Decimal("5000.00"), closing_day=31, due_day=10,
    )
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    # dia 15 < 31 → fatura de fevereiro; fechamento limitado ao último dia (28)
    stmt = CreditCardService.get_or_create_statement(
        db_session, card, datetime.fromisoformat("2026-02-15T12:00:00")
    )
    assert stmt.month == "2026-02"
    assert stmt.closing_date.day == 28
