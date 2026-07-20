from datetime import datetime
from decimal import Decimal
from app.services.credit_card_service import CreditCardService
from app.models.credit_card import CreditCard
from sqlmodel import Session

def test_get_or_create_statement_december_overflow(db_session: Session, seed_ws):
    card = CreditCard(name="Card", workspace_id=seed_ws["ws"].id, closing_day=25, due_day=5, limit=Decimal("1000"))
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    
    # Dec 26 -> Should route to next year's January statement
    tx_date = datetime(2025, 12, 26)
    statement = CreditCardService.get_or_create_statement(db_session, card, tx_date)
    
    assert statement.month == "2026-01"
    assert statement.closing_date.year == 2026
    assert statement.closing_date.month == 1
    assert statement.due_date.year == 2026
    assert statement.due_date.month == 2
    assert statement.due_date.day == 5

def test_get_or_create_statement_due_after_closing(db_session: Session, seed_ws):
    # Due day (10) > Closing day (5) -> Same month
    card = CreditCard(name="Card", workspace_id=seed_ws["ws"].id, closing_day=5, due_day=10, limit=Decimal("1000"))
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    
    tx_date = datetime(2026, 5, 10) # After closing, next statement
    statement = CreditCardService.get_or_create_statement(db_session, card, tx_date)
    
    assert statement.month == "2026-06"
    assert statement.closing_date.month == 6
    assert statement.due_date.month == 6
    assert statement.due_date.day == 10

def test_get_or_create_statement_december_due_overflow(db_session: Session, seed_ws):
    # Transaction in November, closes after 25th (Nov 26).
    # Month = 12. If due_day < closing_day, due_date overflows to Jan next year.
    card = CreditCard(name="Card", workspace_id=seed_ws["ws"].id, closing_day=25, due_day=5, limit=Decimal("1000"))
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    
    tx_date = datetime(2026, 11, 26)
    statement = CreditCardService.get_or_create_statement(db_session, card, tx_date)
    
    assert statement.month == "2026-12"
    assert statement.due_date.year == 2027
    assert statement.due_date.month == 1
    assert statement.due_date.day == 5
