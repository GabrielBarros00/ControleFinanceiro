from sqlmodel import Session
from datetime import datetime, date
from decimal import Decimal
from app.models.transaction import Transaction, TransactionStatus
from app.models.recurring import RecurringExpense
from app.models.estimate import MonthlyEstimate
from app.models.credit_card import CreditCard, CardStatement, StatementStatus
from app.services.forecast_service import ForecastService
from app.services.credit_card_service import CreditCardService

from unittest.mock import patch

def test_forecast_calculation(db_session: Session, seed_ws):
    workspace_id = seed_ws["ws"].id
    target_month = date(2026, 5, 1)
    
    # We MUST patch where it is USED (imported), not where it is defined.
    # In app/services/forecast_service.py: import calendar, date (from datetime)
    with patch("app.services.forecast_service.date") as mock_date:
        # Mock today as May 6th, 2026
        mock_date.today.return_value = date(2026, 5, 6)
        # Re-implement side effect so date(2026, 5, 1) etc still work
        mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
        
        # 1. Setup: 3 transactions in May (Total 300)
        t1 = Transaction(title="T1", total_amount=Decimal("100.00"), transaction_date=datetime(2026, 5, 1), workspace_id=workspace_id)
        t2 = Transaction(title="T2", total_amount=100.00, transaction_date=datetime(2026, 5, 2), workspace_id=workspace_id)
        t3 = Transaction(title="T3", total_amount=100.00, transaction_date=datetime(2026, 5, 3), workspace_id=workspace_id)
        db_session.add_all([t1, t2, t3])
        
        # 2. Setup: 1 recurring expense on May 15th (1000.00)
        r1 = RecurringExpense(title="Rent", base_amount=1000.00, day_of_month=15, workspace_id=workspace_id, is_active=True)
        db_session.add(r1)
        
        # 3. Setup: Monthly Budget (2500.00)
        e1 = MonthlyEstimate(category="All", amount=2500.00, month="2026-05", workspace_id=workspace_id, user_id=seed_ws["user"].id)
        db_session.add(e1)
        
        db_session.commit()
        
        # Act
        projection = ForecastService.get_monthly_projection(db_session, workspace_id, target_month)
        
        # Assert
        assert projection["actual_spent"] == Decimal("300.00")
        # Daily avg = 300 / 6 (today is 6th) = 50.00
        assert projection["daily_average"] == Decimal("50.00")
        
        # Projected EOM = 300 + (50 * 25 remaining days) + 1000 (rent on 15th)
        # 300 + 1250 + 1000 = 2550
        assert projection["projected_eom"] == Decimal("2550.00")
        assert projection["is_over_budget"] is True

def test_forecast_past_month(db_session: Session, seed_ws):
    workspace_id = seed_ws["ws"].id
    target_month = date(2026, 4, 1) # April (Past)
    
    with patch("app.services.forecast_service.date") as mock_date:
        mock_date.today.return_value = date(2026, 5, 6)
        mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
        
        # 400 spent in April
        t1 = Transaction(title="T1", total_amount=Decimal("400.00"), transaction_date=datetime(2026, 4, 10), workspace_id=workspace_id)
        db_session.add(t1)
        db_session.commit()
        
        projection = ForecastService.get_monthly_projection(db_session, workspace_id, target_month)
        
        assert projection["actual_spent"] == Decimal("400.00")
        assert projection["remaining_days"] == 0
        assert projection["fixed_costs_pending"] == 0

def test_forecast_future_month(db_session: Session, seed_ws):
    workspace_id = seed_ws["ws"].id
    target_month = date(2026, 6, 1) # June (Future)
    
    with patch("app.services.forecast_service.date") as mock_date:
        mock_date.today.return_value = date(2026, 5, 6)
        mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
        
        # Recurring expense in future month (should all be pending)
        r1 = RecurringExpense(title="Rent", base_amount=1000.00, day_of_month=15, workspace_id=workspace_id, is_active=True)
        db_session.add(r1)
        db_session.commit()
        
        projection = ForecastService.get_monthly_projection(db_session, workspace_id, target_month)
        
        assert projection["actual_spent"] == Decimal("0.00")
        assert projection["remaining_days"] == 30 # June has 30 days
        assert projection["fixed_costs_pending"] == Decimal("1000.00")


def test_forecast_uses_frozen_statement_total_after_close(db_session: Session, seed_ws):
    """F-06: fatura FECHADA entra no forecast pelo total CONGELADO no fechamento,
    não pelo recomputado. Editar uma transação de fatura já fechada não pode mudar
    o caixa projetado — senão o forecast diverge do valor faturado no cartão."""
    workspace_id = seed_ws["ws"].id
    target_month = date(2026, 5, 1)

    with patch("app.services.forecast_service.date") as mock_date:
        mock_date.today.return_value = date(2026, 5, 6)
        mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)

        card = CreditCard(
            name="Visa", limit=Decimal("5000.00"),
            closing_day=1, due_day=10, workspace_id=workspace_id,
        )
        db_session.add(card)
        db_session.flush()

        stmt = CardStatement(
            card_id=card.id, month="2026-05",
            closing_date=datetime(2026, 5, 1),
            due_date=datetime(2026, 5, 10),
            status=StatementStatus.open,
        )
        db_session.add(stmt)
        db_session.flush()

        tx = Transaction(
            title="Compra", total_amount=Decimal("200.00"),
            transaction_date=datetime(2026, 4, 20), workspace_id=workspace_id,
            statement_id=stmt.id, status=TransactionStatus.confirmed, currency="BRL",
        )
        db_session.add(tx)
        db_session.commit()

        # Fecha a fatura: congela o total em 200
        CreditCardService.close_statement(db_session, stmt)
        db_session.commit()

        # Edita a transação DEPOIS do fechamento: sobe para 999
        tx.total_amount = Decimal("999.00")
        db_session.add(tx)
        db_session.commit()

        projection = ForecastService.get_monthly_projection(db_session, workspace_id, target_month)
        # Congelado (200), não recomputado (999)
        assert projection["card_statements_pending"] == Decimal("200.00")
        # E bate com o comprometido do cartão (mesma definição)
        assert CreditCardService.card_committed(db_session, card) == Decimal("200.00")
