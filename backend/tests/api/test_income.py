import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session
from app.main import app
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.models.income import Income
from app.core.jwt import create_access_token

client = TestClient(app)

@pytest.fixture
def income_setup(db_session: Session):
    u1 = User(name="User 1", email="u1@income.com", password_hash="hash")
    u2 = User(name="User 2", email="u2@income.com", password_hash="hash")
    db_session.add_all([u1, u2])
    db_session.commit()
    db_session.refresh(u1)
    db_session.refresh(u2)
    
    ws1 = Workspace(name="WS 1", created_by_user_id=u1.id)
    db_session.add(ws1)
    db_session.commit()
    db_session.refresh(ws1)
    db_session.add(WorkspaceMembership(workspace_id=ws1.id, user_id=u1.id, role="owner"))
    db_session.commit()
    
    token1 = create_access_token(data={"sub": str(u1.id)})
    token2 = create_access_token(data={"sub": str(u2.id)})
    
    return {
        "u1": u1, "u2": u2, 
        "ws1": ws1, 
        "headers1": {"Cookie": f"access_token={token1}"},
        "headers2": {"Cookie": f"access_token={token2}"}
    }

def test_create_income_success(income_setup, override_get_session):
    ws_id = income_setup["ws1"].id
    payload = {
        "title": "Salary",
        "amount": 5000.0,
        "category": "Salary",
        "received_at": "2026-05-10T10:00:00"
    }
    response = client.post(f"/api/v1/workspaces/{ws_id}/income/", json=payload, headers=income_setup["headers1"])
    assert response.status_code == 200
    assert response.json()["title"] == "Salary"

def test_create_income_forbidden(income_setup, override_get_session):
    ws_id = income_setup["ws1"].id
    payload = {"title": "Hack", "amount": 100, "category": "X", "received_at": "2026-05-10T10:00:00"}
    # User 2 is not in WS 1
    response = client.post(f"/api/v1/workspaces/{ws_id}/income/", json=payload, headers=income_setup["headers2"])
    assert response.status_code == 403

def test_list_income_success(db_session: Session, income_setup, override_get_session):
    ws_id = income_setup["ws1"].id
    u1_id = income_setup["u1"].id
    
    # Create one income
    db_session.add(Income(title="I1", amount=100, category="C", workspace_id=ws_id, user_id=u1_id))
    db_session.commit()
    
    response = client.get(f"/api/v1/workspaces/{ws_id}/income/", headers=income_setup["headers1"])
    assert response.status_code == 200
    assert len(response.json()) == 1

def test_list_income_forbidden(income_setup, override_get_session):
    ws_id = income_setup["ws1"].id
    response = client.get(f"/api/v1/workspaces/{ws_id}/income/", headers=income_setup["headers2"])
    assert response.status_code == 403
