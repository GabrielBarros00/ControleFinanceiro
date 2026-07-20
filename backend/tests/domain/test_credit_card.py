from datetime import datetime
from sqlmodel import Session
from app.models.credit_card import CreditCard
from app.services.credit_card_service import CreditCardService

def test_get_or_create_statement_current_month(db_session: Session, seed_ws):
    # Card with closing on 25th
    card = CreditCard(name="Test Card", limit=1000, closing_day=25, due_day=5, workspace_id=seed_ws["ws"].id)
    db_session.add(card)
    db_session.commit()

    # Transaction on May 10th (before closing)
    t_date = datetime(2026, 5, 10)
    statement = CreditCardService.get_or_create_statement(db_session, card, t_date)

    assert statement.month == "2026-05"
    assert statement.closing_date.day == 25
    assert statement.due_date.month == 6 # Due on June 5th

def test_get_or_create_statement_next_month(db_session: Session, seed_ws):
    card = CreditCard(name="Test Card 2", limit=1000, closing_day=25, due_day=5, workspace_id=seed_ws["ws"].id)
    db_session.add(card)
    db_session.commit()

    # Transaction on May 26th (after closing)
    t_date = datetime(2026, 5, 26)
    statement = CreditCardService.get_or_create_statement(db_session, card, t_date)

    assert statement.month == "2026-06"
    assert statement.closing_date.month == 6
    assert statement.due_date.month == 7
