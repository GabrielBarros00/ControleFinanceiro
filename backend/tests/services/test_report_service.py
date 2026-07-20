from sqlmodel import Session
from datetime import date, datetime
from decimal import Decimal
from app.models.transaction import Transaction, TransactionItem
from app.models.income import Income
from app.models.category import Category
from app.services.report_service import ReportService

def test_get_summary_with_data(db_session: Session, seed_ws):
    workspace_id = seed_ws["ws"].id
    user = seed_ws["user"]
    target_month = date(2026, 5, 1)

    # Setup: Categorias do workspace
    cat_a = Category(workspace_id=workspace_id, name="Mercado")
    cat_b = Category(workspace_id=workspace_id, name="Transporte")
    db_session.add_all([cat_a, cat_b])
    db_session.commit()
    db_session.refresh(cat_a)
    db_session.refresh(cat_b)

    # Setup: Expenses
    t1 = Transaction(title="T1", total_amount=Decimal("100.00"), transaction_date=datetime(2026, 5, 1), workspace_id=workspace_id, created_by_user_id=user.id)
    db_session.add(t1)
    db_session.flush()

    item1 = TransactionItem(transaction_id=t1.id, category_id=cat_a.id, amount=Decimal("60.00"), description="Item 1", title="Item 1")
    item2 = TransactionItem(transaction_id=t1.id, category_id=cat_b.id, amount=Decimal("40.00"), description="Item 2", title="Item 2")
    db_session.add_all([item1, item2])
    
    # Setup: Income
    i1 = Income(amount=Decimal("5000.00"), received_at=datetime(2026, 5, 5), workspace_id=workspace_id, title="Salary", user_id=user.id)
    db_session.add(i1)
    
    db_session.commit()
    
    # Act
    summary = ReportService.get_summary(db_session, workspace_id, target_month)
    
    # Assert
    assert summary["total_expenses"] == 100.0
    assert summary["total_income"] == 5000.0
    assert summary["net_savings"] == 4900.0
    assert len(summary["categories"]) == 2
    # Nomes de categoria resolvidos a partir da tabela Category
    cats = sorted(summary["categories"], key=lambda x: x["name"])
    assert cats[0]["name"] == "Mercado"
    assert cats[0]["value"] == 60.0
    assert cats[1]["name"] == "Transporte"
    assert cats[1]["value"] == 40.0

def test_get_summary_empty(db_session: Session):
    workspace_id = 1
    target_month = date(2026, 5, 1)
    
    summary = ReportService.get_summary(db_session, workspace_id, target_month)
    
    assert summary["total_expenses"] == 0.0
    assert summary["total_income"] == 0.0
    assert summary["net_savings"] == 0.0
    assert summary["categories"] == []

def test_get_summary_excludes_and_counts_foreign_currency(db_session: Session, seed_ws):
    """E5/F-04: lançamento em moeda != base fica FORA dos totais, mas é contado."""
    workspace_id = seed_ws["ws"].id
    user = seed_ws["user"]
    target_month = date(2026, 5, 1)

    brl = Transaction(
        title="BRL", total_amount=Decimal("100.00"), transaction_date=datetime(2026, 5, 2),
        workspace_id=workspace_id, created_by_user_id=user.id, currency="BRL",
    )
    usd = Transaction(
        title="USD", total_amount=Decimal("50.00"), transaction_date=datetime(2026, 5, 3),
        workspace_id=workspace_id, created_by_user_id=user.id, currency="USD",
    )
    db_session.add_all([brl, usd])
    db_session.commit()

    summary = ReportService.get_summary(db_session, workspace_id, target_month)
    assert summary["total_expenses"] == Decimal("100.00")   # USD não somado
    assert summary["base_currency"] == "BRL"
    assert summary["excluded_foreign_count"] == 1


def test_get_last_6_months(db_session: Session):
    workspace_id = 1
    # Just verify it doesn't crash and returns 6 items
    results = ReportService.get_last_6_months(db_session, workspace_id)
    assert len(results) == 6
    for item in results:
        assert "name" in item
        assert "expenses" in item
        assert "income" in item
