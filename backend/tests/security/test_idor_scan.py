import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session
from app.main import app
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.models.transaction import Transaction
from app.models.income import Income
from app.models.credit_card import CreditCard
from app.models.recurring import RecurringExpense
from app.core.jwt import create_access_token
import datetime

client = TestClient(app)

@pytest.fixture
def idor_setup(db_session: Session):
    # User 1 (Attacker)
    u1 = User(name="Attacker", email="attacker@test.com", password_hash="hash")
    # User 2 (Victim)
    u2 = User(name="Victim", email="victim@test.com", password_hash="hash")
    db_session.add_all([u1, u2])
    db_session.commit()
    
    # WS1 (Attacker's)
    ws1 = Workspace(name="Attacker WS", created_by_user_id=u1.id)
    # WS2 (Victim's)
    ws2 = Workspace(name="Victim WS", created_by_user_id=u2.id)
    db_session.add_all([ws1, ws2])
    db_session.commit()
    
    # Attacker belongs to WS1
    db_session.add(WorkspaceMembership(workspace_id=ws1.id, user_id=u1.id, role="owner"))
    # Victim belongs to WS2
    db_session.add(WorkspaceMembership(workspace_id=ws2.id, user_id=u2.id, role="owner"))
    db_session.commit()
    
    # Victim's Private Data
    # 1. Transaction
    tx = Transaction(title="Secret Tx", total_amount=100, transaction_date=datetime.datetime.now(), workspace_id=ws2.id, created_by_user_id=u2.id)
    # 2. Income
    inc = Income(title="Secret Pay", amount=5000, received_at=datetime.datetime.now(), workspace_id=ws2.id, user_id=u2.id)
    # 3. Credit Card
    card = CreditCard(name="Victim Card", limit=1000, closing_day=1, due_day=10, workspace_id=ws2.id)
    # 4. Recurring
    rec = RecurringExpense(title="Rent", base_amount=1000, day_of_month=1, workspace_id=ws2.id)
    
    db_session.add_all([tx, inc, card, rec])
    db_session.commit()
    db_session.refresh(tx)
    db_session.refresh(inc)
    db_session.refresh(card)
    db_session.refresh(rec)
    
    token1 = create_access_token(data={"sub": str(u1.id)})
    
    return {
        "attacker_headers": {"Cookie": f"access_token={token1}"},
        "victim_ws_id": ws2.id,
        "victim_tx_id": tx.id,
        "victim_inc_id": inc.id,
        "victim_card_id": card.id,
        "victim_rec_id": rec.id
    }

def test_idor_get_workspace(idor_setup, override_get_session):
    ws_id = idor_setup["victim_ws_id"]
    # Should fail because Attacker is not in Victim WS
    response = client.get(f"/api/v1/workspaces/{ws_id}", headers=idor_setup["attacker_headers"])
    assert response.status_code in [403, 404]

def test_idor_list_transactions(idor_setup, override_get_session):
    ws_id = idor_setup["victim_ws_id"]
    response = client.get(f"/api/v1/workspaces/{ws_id}/transactions/", headers=idor_setup["attacker_headers"])
    assert response.status_code in [403, 404]

def test_idor_get_transaction(idor_setup, override_get_session):
    ws_id = idor_setup["victim_ws_id"]
    tx_id = idor_setup["victim_tx_id"]
    response = client.get(f"/api/v1/workspaces/{ws_id}/transactions/{tx_id}", headers=idor_setup["attacker_headers"])
    assert response.status_code in [403, 404]

def test_idor_list_income(idor_setup, override_get_session):
    ws_id = idor_setup["victim_ws_id"]
    response = client.get(f"/api/v1/workspaces/{ws_id}/income/", headers=idor_setup["attacker_headers"])
    assert response.status_code in [403, 404]

def test_idor_analytics_summary(idor_setup, override_get_session):
    ws_id = idor_setup["victim_ws_id"]
    response = client.get(f"/api/v1/workspaces/{ws_id}/analytics/summary", headers=idor_setup["attacker_headers"])
    assert response.status_code in [403, 404]

def test_idor_list_credit_cards(idor_setup, override_get_session):
    ws_id = idor_setup["victim_ws_id"]
    response = client.get(f"/api/v1/workspaces/{ws_id}/credit-cards/", headers=idor_setup["attacker_headers"])
    assert response.status_code in [403, 404]

def test_idor_list_recurring(idor_setup, override_get_session):
    ws_id = idor_setup["victim_ws_id"]
    response = client.get(f"/api/v1/workspaces/{ws_id}/recurring", headers=idor_setup["attacker_headers"])
    assert response.status_code in [403, 404]

def test_idor_get_recurring(idor_setup, override_get_session):
    ws_id = idor_setup["victim_ws_id"]
    rec_id = idor_setup["victim_rec_id"]
    response = client.get(f"/api/v1/workspaces/{ws_id}/recurring/{rec_id}", headers=idor_setup["attacker_headers"])
    assert response.status_code in [403, 404]

def test_idor_list_debts(idor_setup, override_get_session):
    ws_id = idor_setup["victim_ws_id"]
    response = client.get(f"/api/v1/workspaces/{ws_id}/debts", headers=idor_setup["attacker_headers"])
    assert response.status_code in [403, 404]
