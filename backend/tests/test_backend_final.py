import pytest
import io
from decimal import Decimal
from datetime import datetime, UTC, date
from sqlmodel import Session, select

from app.core.jwt import create_access_token, create_refresh_token
from app.services.csv_parser import CSVParserService, CSVColumnMapping
from app.services.recurring_service import RecurringService
from app.models.recurring import RecurringExpense
from app.models.transaction import Transaction, TransactionStatus
from app.models.audit import AuditLog, ActionType

def test_jwt_default_expiry():
    # Hit line 12 and 24 in jwt.py
    token = create_access_token(data={"sub": "1"})
    assert token is not None
    
    refresh = create_refresh_token(data={"sub": "1"})
    assert refresh is not None

def test_csv_parser_error_paths():
    # Hit lines 33, 39-40, 53-54 in csv_parser.py
    mapping = CSVColumnMapping(
        date_column="date",
        description_column="desc",
        amount_column="amt"
    )
    
    # Campos ausentes: nenhuma linha válida, 1 pulada com motivo (ADR 0008)
    csv_1 = "date,desc,amt\n,Lunch,"
    res_1 = CSVParserService.parse(io.StringIO(csv_1), mapping)
    assert res_1["rows"] == []
    assert len(res_1["skipped"]) == 1

    # Data inválida
    csv_2 = "date,desc,amt\nINVALID,Lunch,10.00"
    res_2 = CSVParserService.parse(io.StringIO(csv_2), mapping)
    assert res_2["rows"] == []
    assert len(res_2["skipped"]) == 1

    # Valor inválido
    csv_3 = "date,desc,amt\n2026-01-01,Lunch,BOOM"
    res_3 = CSVParserService.parse(io.StringIO(csv_3), mapping)
    assert res_3["rows"] == []
    assert len(res_3["skipped"]) == 1

def test_recurring_service_branch_existing(db_session: Session, seed_ws):
    # Setup template
    template = RecurringExpense(
        title="Monthly",
        base_amount=Decimal("100"),
        day_of_month=1,
        workspace_id=seed_ws["ws"].id,
        is_active=True
    )
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)
    
    # Hit line 27: existing monthly instance
    tx1 = RecurringService.get_or_create_monthly_instance(db_session, template.id, 2026, 1)
    tx2 = RecurringService.get_or_create_monthly_instance(db_session, template.id, 2026, 1)
    assert tx1.id == tx2.id

def test_recurring_service_branch_inactive(db_session: Session, seed_ws):
    # Hit line 32: inactive template
    template = RecurringExpense(
        title="Inactive",
        base_amount=Decimal("100"),
        day_of_month=1,
        workspace_id=seed_ws["ws"].id,
        is_active=False
    )
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)
    
    with pytest.raises(ValueError, match="Despesa recorrente não encontrada ou inativa"):
        RecurringService.get_or_create_monthly_instance(db_session, template.id, 2026, 1)

def test_recurring_service_sync_no_txs(db_session: Session, seed_ws):
    # Hit line 66: if unpaid_txs: db.commit() -> branch where it is false
    template = RecurringExpense(
        title="Empty Sync",
        base_amount=Decimal("100"),
        day_of_month=1,
        workspace_id=seed_ws["ws"].id,
        is_active=True
    )
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)
    
    # No transactions for this template yet
    RecurringService.sync_unpaid_instances(db_session, template.id)
    # Should not crash

def test_recurring_service_sync_with_txs(db_session: Session, seed_ws):
    template = RecurringExpense(
        title="Sync With Txs",
        base_amount=Decimal("100"),
        day_of_month=1,
        workspace_id=seed_ws["ws"].id,
        is_active=True
    )
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)
    
    # Create an unpaid instance for the current month
    today = date.today()
    billing_month = f"{today.year:04d}-{today.month:02d}"
    tx = Transaction(
        title="Old Title",
        description="Sync Test",
        total_amount=Decimal("100"),
        status=TransactionStatus.pending,
        workspace_id=seed_ws["ws"].id,
        created_by_user_id=seed_ws["user"].id,
        recurring_expense_id=template.id,
        billing_month=billing_month,
        transaction_date=datetime(today.year, today.month, today.day, tzinfo=UTC)
    )
    db_session.add(tx)
    db_session.commit()

    # Update template
    template.base_amount = Decimal("200")
    db_session.add(template)
    db_session.commit()

    # Sync
    RecurringService.sync_unpaid_instances(db_session, template.id)

    # Check if transaction was updated
    db_session.refresh(tx)
    assert tx.total_amount == Decimal("200")
    assert tx.title == "Sync With Txs"

def test_audit_log_update_trigger(db_session: Session):
    from app.models.workspace import Workspace
    ws = Workspace(name="Audit Test", owner_id=1)
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)
    
    ws.name = "Audit Updated"
    db_session.add(ws)
    db_session.commit()
    
    # Check if audit log was created
    log = db_session.exec(select(AuditLog).where(AuditLog.resource_type == "Workspace", AuditLog.action == ActionType.update)).first()
    assert log is not None


def test_financing_price_zero_interest():
    from app.services.financing_service import FinancingService
    from app.models.financing import AmortizationMethod

    # Hit line 50: zero interest path in PRICE
    plan = FinancingService.calculate_amortization_schedule(
        total_amount=Decimal("1000"),
        interest_rate=Decimal("0"),
        installments_count=10,
        method=AmortizationMethod.PRICE,
        start_date=date(2026, 1, 1)
    )
    assert len(plan) == 10
    assert plan[0].total_amount == Decimal("100")

def test_audit_log_skip_self_delete(db_session: Session):
    # Hit line 77 in audit_events.py (recursive skip on delete)
    log = AuditLog(
        action=ActionType.delete,
        resource_type="MetaDel",
        new_values={"msg": "bye"}
    )
    db_session.add(log)
    db_session.commit()

    db_session.delete(log)
    db_session.commit()

    # Ensure no NEW audit log was created for the deletion of the audit log itself
    logs = db_session.exec(select(AuditLog).where(AuditLog.resource_type == "AuditLog")).all()
    assert len(logs) == 0

@pytest.mark.asyncio
async def test_root_endpoint_and_lifespan():
    from fastapi.testclient import TestClient
    from app.main import app
    # Using 'with' triggers lifespan
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.json() == {"message": "Welcome to Controle Financeiro V4 API"}

