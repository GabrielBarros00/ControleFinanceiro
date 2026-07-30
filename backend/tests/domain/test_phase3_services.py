from datetime import datetime, date, UTC
from decimal import Decimal

from sqlmodel import Session

from app.models.user import User
from app.models.workspace import Workspace
from app.models.transaction import Transaction, TransactionStatus
from app.models.recurring import RecurringExpense
from app.services.forecast_service import ForecastService
from app.services.recurring_service import RecurringService


def _setup_ws(db: Session):
    user = User(name="F", email="f@svc.com", password_hash="hash")
    ws = Workspace(name="Svc WS")
    db.add_all([user, ws])
    db.commit()
    db.refresh(user)
    db.refresh(ws)
    return user, ws


def test_forecast_does_not_double_count_instanced_recurring(db_session: Session):
    """Template recorrente com instância já lançada no mês não entra de novo
    em fixed_costs_pending."""
    user, ws = _setup_ws(db_session)
    today = date.today()

    template = RecurringExpense(
        title="Aluguel", base_amount=Decimal("1000.00"), day_of_month=28,
        workspace_id=ws.id, is_active=True,
    )
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)

    # Instância do mês já lançada (dia 28, futura)
    db_session.add(Transaction(
        title="Aluguel", total_amount=Decimal("1000.00"),
        transaction_date=datetime(today.year, today.month, 28),
        billing_month=today.strftime("%Y-%m"),
        workspace_id=ws.id, created_by_user_id=user.id,
        recurring_expense_id=template.id,
        status=TransactionStatus.pending,
    ))
    db_session.commit()

    result = ForecastService.get_monthly_projection(db_session, ws.id, today)
    # A instância está em actual_spent; o template NÃO deve aparecer em fixed pendente
    assert result["fixed_costs_pending"] == Decimal("0.00")
    assert result["actual_spent"] == Decimal("1000.00")


def test_recurring_does_not_resurrect_deleted_instance(db_session: Session):
    """Instância excluída pelo usuário (tombstone) não é recriada pelo serviço."""
    user, ws = _setup_ws(db_session)
    today = date.today()

    template = RecurringExpense(
        title="Academia", base_amount=Decimal("120.00"), day_of_month=5,
        workspace_id=ws.id, is_active=True,
    )
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)

    # Cria a instância do mês e depois exclui (soft)
    tx = RecurringService.get_or_create_monthly_instance(db_session, template.id, today.year, today.month)
    assert tx is not None
    tx.deleted_at = datetime.now(UTC)
    db_session.add(tx)
    db_session.commit()

    # Tombstone respeitado: não ressuscita
    result = RecurringService.get_or_create_monthly_instance(db_session, template.id, today.year, today.month)
    assert result is None
