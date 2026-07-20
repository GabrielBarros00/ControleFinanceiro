from fastapi.testclient import TestClient
from sqlmodel import Session
from app.main import app
from app.models.transaction import Transaction, TransactionItem
from app.models.category import Category
from decimal import Decimal
import datetime

client = TestClient(app)


def _make_categories(db_session, ws_id, names=("Cat A", "Cat B")):
    cats = [Category(workspace_id=ws_id, name=n) for n in names]
    db_session.add_all(cats)
    db_session.commit()
    for c in cats:
        db_session.refresh(c)
    return cats


def test_create_transaction_complex(db_session: Session, setup_data, override_get_session):
    ws1 = setup_data["ws1"]
    u1 = setup_data["u1"]
    cat_a, cat_b = _make_categories(db_session, ws1.id)

    payload = {
        "title": "Complex Tx",
        "total_amount": 100.0,
        "transaction_date": "2026-05-10T10:00:00",
        "payers": [{"user_id": u1.id, "amount": 100.0}],
        "splits": [
            {"user_id": u1.id, "split_method": "percentage", "input_value": 100.0}
        ],
        "items": [
            {"title": "Item 1", "amount": 60.0, "category_id": cat_a.id},
            {"title": "Item 2", "amount": 40.0, "category_id": cat_b.id}
        ]
    }
    
    response = client.post(f"/api/v1/workspaces/{ws1.id}/transactions/", json=payload, headers=setup_data["headers1"])
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Complex Tx"
    assert len(data["items"]) == 2

def test_create_transaction_payer_mismatch(setup_data, override_get_session):
    ws1 = setup_data["ws1"]
    u1 = setup_data["u1"]
    
    payload = {
        "title": "Bad Payer Sum",
        "total_amount": 100.0,
        "transaction_date": "2026-05-10T10:00:00",
        "payers": [{"user_id": u1.id, "amount": 50.0}], # Should be 100
        "splits": [{"user_id": u1.id, "split_method": "equal", "input_value": 0}]
    }
    
    response = client.post(f"/api/v1/workspaces/{ws1.id}/transactions/", json=payload, headers=setup_data["headers1"])
    assert response.status_code == 400

def test_list_transactions_filters(db_session: Session, setup_data, override_get_session):
    ws1 = setup_data["ws1"]
    u1 = setup_data["u1"]
    
    tx1 = Transaction(title="Past", total_amount=10, transaction_date=datetime.datetime(2026, 4, 1), billing_month="2026-04", workspace_id=ws1.id, created_by_user_id=u1.id)
    tx2 = Transaction(title="Current Lunch", total_amount=20, transaction_date=datetime.datetime(2026, 5, 1), billing_month="2026-05", workspace_id=ws1.id, created_by_user_id=u1.id)
    tx3 = Transaction(title="Current Dinner", total_amount=30, transaction_date=datetime.datetime(2026, 5, 2), billing_month="2026-05", workspace_id=ws1.id, created_by_user_id=u1.id)
    
    db_session.add_all([tx1, tx2, tx3])
    db_session.commit()
    
    # Test month filter
    response = client.get(f"/api/v1/workspaces/{ws1.id}/transactions/?month=2026-05", headers=setup_data["headers1"])
    assert len(response.json()["items"]) == 2
    
    # Test search filter
    response = client.get(f"/api/v1/workspaces/{ws1.id}/transactions/?search=Dinner", headers=setup_data["headers1"])
    assert len(response.json()["items"]) == 1

def test_get_transaction_success(db_session: Session, setup_data, override_get_session):
    ws1 = setup_data["ws1"]
    u1 = setup_data["u1"]
    tx = Transaction(title="Success", total_amount=10, transaction_date=datetime.datetime.now(), workspace_id=ws1.id, created_by_user_id=u1.id)
    db_session.add(tx)
    db_session.commit()
    db_session.refresh(tx)
    
    response = client.get(f"/api/v1/workspaces/{ws1.id}/transactions/{tx.id}", headers=setup_data["headers1"])
    assert response.status_code == 200
    assert response.json()["title"] == "Success"

def test_transaction_security_isolation(db_session: Session, setup_data, override_get_session):
    ws1 = setup_data["ws1"]
    ws2 = setup_data["ws2"]
    u2 = setup_data["u2"]
    
    tx_ws2 = Transaction(title="Secret", total_amount=100, transaction_date=datetime.datetime.now(), workspace_id=ws2.id, created_by_user_id=u2.id)
    db_session.add(tx_ws2)
    db_session.commit()
    db_session.refresh(tx_ws2)
    
    response = client.get(f"/api/v1/workspaces/{ws2.id}/transactions/{tx_ws2.id}", headers=setup_data["headers1"])
    assert response.status_code == 403
    
    response = client.get(f"/api/v1/workspaces/{ws1.id}/transactions/{tx_ws2.id}", headers=setup_data["headers1"])
    assert response.status_code == 404

def test_bulk_create_transactions(setup_data, override_get_session):
    ws1 = setup_data["ws1"]
    payload = [
        {"title": "Import 1", "total_amount": 10.5, "transaction_date": "2026-05-01T10:00:00Z"},
        {"title": "Import 2", "total_amount": 20.0, "transaction_date": "2026-05-02T10:00:00Z"}
    ]
    response = client.post(f"/api/v1/workspaces/{ws1.id}/transactions/bulk", json=payload, headers=setup_data["headers1"])
    assert response.status_code == 200
    assert response.json()["created"] == 2

def test_update_transaction(db_session: Session, setup_data, override_get_session):
    ws1 = setup_data["ws1"]
    u1 = setup_data["u1"]
    tx = Transaction(title="Old", total_amount=10, transaction_date=datetime.datetime.now(), workspace_id=ws1.id, created_by_user_id=u1.id)
    db_session.add(tx)
    db_session.commit()
    db_session.refresh(tx)
    
    payload = {"title": "New Title"}
    response = client.put(f"/api/v1/workspaces/{ws1.id}/transactions/{tx.id}", json=payload, headers=setup_data["headers1"])
    assert response.status_code == 200
    assert response.json()["title"] == "New Title"

from app.models.credit_card import CreditCard

def test_create_transaction_with_credit_card(db_session: Session, setup_data, override_get_session):
    ws1 = setup_data["ws1"]
    u1 = setup_data["u1"]
    card = CreditCard(name="MasterCard", workspace_id=ws1.id, closing_day=25, due_day=5, limit=Decimal("10000.00"))
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    
    payload = {
        "title": "Card Tx",
        "total_amount": 50.0,
        "transaction_date": "2026-05-10T10:00:00",
        "credit_card_id": card.id,
        "payers": [{"user_id": u1.id, "amount": 50.0}],
        "splits": [{"user_id": u1.id, "split_method": "equal", "input_value": 0}]
    }
    
    response = client.post(f"/api/v1/workspaces/{ws1.id}/transactions/", json=payload, headers=setup_data["headers1"])
    assert response.status_code == 200
    assert response.json()["statement_id"] is not None

def test_list_transactions_category_filter(db_session: Session, setup_data, override_get_session):
    ws1 = setup_data["ws1"]
    u1 = setup_data["u1"]
    cat, = _make_categories(db_session, ws1.id, names=("Comida",))
    tx = Transaction(title="Food", total_amount=15, transaction_date=datetime.datetime.now(), workspace_id=ws1.id, created_by_user_id=u1.id)
    db_session.add(tx)
    db_session.commit()
    db_session.refresh(tx)
    item = TransactionItem(title="Pizza", amount=15, category_id=cat.id, transaction_id=tx.id)
    db_session.add(item)
    db_session.commit()
    response = client.get(f"/api/v1/workspaces/{ws1.id}/transactions/?category_id={cat.id}", headers=setup_data["headers1"])
    assert len(response.json()["items"]) == 1

def test_transactions_forbidden(db_session: Session, setup_data, override_get_session):
    ws2 = setup_data["ws2"]
    headers1 = setup_data["headers1"]
    u1 = setup_data["u1"]
    u2 = setup_data["u2"]
    
    payload = {
        "title": "X", "total_amount": 10.0, "transaction_date": "2026-05-10T10:00:00",
        "payers": [{"user_id": u1.id, "amount": 10.0}],
        "splits": [{"user_id": u1.id, "split_method": "equal", "input_value": 0}]
    }
    assert client.post(f"/api/v1/workspaces/{ws2.id}/transactions/", json=payload, headers=headers1).status_code == 403
    assert client.get(f"/api/v1/workspaces/{ws2.id}/transactions/", headers=headers1).status_code == 403
    assert client.post(f"/api/v1/workspaces/{ws2.id}/transactions/bulk", json=[], headers=headers1).status_code == 403
    
    tx_ws2 = Transaction(title="S", total_amount=Decimal("1.0"), transaction_date=datetime.datetime.now(), workspace_id=ws2.id, created_by_user_id=u2.id)
    db_session.add(tx_ws2)
    db_session.commit()
    db_session.refresh(tx_ws2)
    assert client.get(f"/api/v1/workspaces/{ws2.id}/transactions/{tx_ws2.id}", headers=headers1).status_code == 403

def test_create_transaction_explicit_billing_month(setup_data, override_get_session):
    ws1 = setup_data["ws1"]
    u1 = setup_data["u1"]
    payload = {
        "title": "Explicit Month", "total_amount": 10.0, "transaction_date": "2026-05-10T10:00:00",
        "billing_month": "2026-06",
        "payers": [{"user_id": u1.id, "amount": 10.0}],
        "splits": [{"user_id": u1.id, "split_method": "equal", "input_value": 0}]
    }
    response = client.post(f"/api/v1/workspaces/{ws1.id}/transactions/", json=payload, headers=setup_data["headers1"])
    assert response.status_code == 200
    assert response.json()["billing_month"] == "2026-06"

def test_create_transaction_invalid_card(setup_data, override_get_session):
    ws1 = setup_data["ws1"]
    u1 = setup_data["u1"]
    payload = {
        "title": "Invalid Card", "total_amount": 10.0, "transaction_date": "2026-05-10T10:00:00",
        "credit_card_id": 9999,
        "payers": [{"user_id": u1.id, "amount": 10.0}],
        "splits": [{"user_id": u1.id, "split_method": "equal", "input_value": 0}]
    }
    # Cartão inexistente é rejeitado (nunca insere FK inválida)
    response = client.post(f"/api/v1/workspaces/{ws1.id}/transactions/", json=payload, headers=setup_data["headers1"])
    assert response.status_code == 400

def test_bulk_create_transactions_minimal(setup_data, override_get_session):
    ws1 = setup_data["ws1"]
    # Linha vazia (valor 0) é pulada; linha válida é criada
    payload = [{}, {"title": "Válida", "total_amount": "12.34"}]
    response = client.post(f"/api/v1/workspaces/{ws1.id}/transactions/bulk", json=payload, headers=setup_data["headers1"])
    assert response.status_code == 200
    assert response.json()["created"] == 1
    assert response.json()["skipped"] == 1

def test_transactions_not_found(setup_data, override_get_session):
    ws1 = setup_data["ws1"]
    headers1 = setup_data["headers1"]
    assert client.get(f"/api/v1/workspaces/{ws1.id}/transactions/9999", headers=headers1).status_code == 404
    assert client.put(f"/api/v1/workspaces/{ws1.id}/transactions/9999", json={"title":"X"}, headers=headers1).status_code == 404

def test_update_transaction_forbidden(db_session: Session, setup_data, override_get_session):
    ws1 = setup_data["ws1"]
    u1 = setup_data["u1"]
    tx = Transaction(title="T1", total_amount=10, transaction_date=datetime.datetime.now(), workspace_id=ws1.id, created_by_user_id=u1.id)
    db_session.add(tx)
    db_session.commit()
    db_session.refresh(tx)
    response = client.put(f"/api/v1/workspaces/{ws1.id}/transactions/{tx.id}", json={"title":"Hacked"}, headers=setup_data["headers2"])
    assert response.status_code == 403

def test_bulk_create_forbidden(setup_data, override_get_session):
    ws1 = setup_data["ws1"]
    response = client.post(f"/api/v1/workspaces/{ws1.id}/transactions/bulk", json=[{}], headers=setup_data["headers2"])
    assert response.status_code == 403

def test_get_transaction_deleted(db_session: Session, setup_data, override_get_session):
    ws1 = setup_data["ws1"]
    u1 = setup_data["u1"]
    tx = Transaction(title="Del", total_amount=10, transaction_date=datetime.datetime.now(), workspace_id=ws1.id, created_by_user_id=u1.id, deleted_at=datetime.datetime.now())
    db_session.add(tx)
    db_session.commit()
    db_session.refresh(tx)
    
    response = client.get(f"/api/v1/workspaces/{ws1.id}/transactions/{tx.id}", headers=setup_data["headers1"])
    assert response.status_code == 404
