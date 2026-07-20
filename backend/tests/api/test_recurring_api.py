import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.models.recurring import RecurringExpense
from sqlmodel import Session, select
from app.core.jwt import create_access_token
from decimal import Decimal

client = TestClient(app)

@pytest.fixture
def auth_header(db_session: Session):
    user = User(name="Test User", email="test@example.com", password_hash="hash")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    
    token = create_access_token(data={"sub": str(user.id)})
    return {"Cookie": f"access_token={token}"}

@pytest.fixture
def test_workspace(db_session: Session, auth_header):
    user = db_session.exec(select(User).where(User.email == "test@example.com")).first()
    
    ws = Workspace(name="Test WS", created_by_user_id=user.id)
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)
    
    membership = WorkspaceMembership(workspace_id=ws.id, user_id=user.id, role="owner") # Dummy role
    db_session.add(membership)
    db_session.commit()
    
    return ws

def test_list_recurring(db_session: Session, auth_header, test_workspace, override_get_session):
    # Setup
    r1 = RecurringExpense(title="Rent", base_amount=Decimal("1000.00"), day_of_month=5, workspace_id=test_workspace.id)
    db_session.add(r1)
    db_session.commit()
    
    response = client.get(f"/api/v1/workspaces/{test_workspace.id}/recurring", headers=auth_header)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "Rent"

def test_get_recurring(db_session: Session, auth_header, test_workspace, override_get_session):
    r1 = RecurringExpense(title="Internet", base_amount=Decimal("100.00"), day_of_month=10, workspace_id=test_workspace.id)
    db_session.add(r1)
    db_session.commit()
    db_session.refresh(r1)
    
    response = client.get(f"/api/v1/workspaces/{test_workspace.id}/recurring/{r1.id}", headers=auth_header)
    assert response.status_code == 200
    assert response.json()["title"] == "Internet"

def test_update_recurring(db_session: Session, auth_header, test_workspace, override_get_session):
    r1 = RecurringExpense(title="Old Name", base_amount=Decimal("50.00"), day_of_month=1, workspace_id=test_workspace.id)
    db_session.add(r1)
    db_session.commit()
    db_session.refresh(r1)
    
    update_data = {"title": "New Name", "base_amount": 75.50}
    response = client.put(f"/api/v1/workspaces/{test_workspace.id}/recurring/{r1.id}", json=update_data, headers=auth_header)
    assert response.status_code == 200
    assert response.json()["title"] == "New Name"
    assert response.json()["base_amount"] == "75.50"

def test_delete_recurring(db_session: Session, auth_header, test_workspace, override_get_session):
    r1 = RecurringExpense(title="To Delete", base_amount=Decimal("10.00"), day_of_month=1, workspace_id=test_workspace.id)
    db_session.add(r1)
    db_session.commit()
    db_session.refresh(r1)
    
    response = client.delete(f"/api/v1/workspaces/{test_workspace.id}/recurring/{r1.id}", headers=auth_header)
    assert response.status_code == 200
    
    # Verify gone
    db_session.expire_all()
    deleted = db_session.get(RecurringExpense, r1.id)
    assert deleted is None

def test_create_recurring_success(db_session: Session, auth_header, test_workspace, override_get_session):
    payload = {
        "title": "Netflix",
        "base_amount": 55.90,
        "day_of_month": 15
    }
    response = client.post(f"/api/v1/workspaces/{test_workspace.id}/recurring", json=payload, headers=auth_header)
    assert response.status_code == 200
    assert response.json()["title"] == "Netflix"
    assert response.json()["base_amount"] == "55.90"

def test_recurring_forbidden(db_session: Session, test_workspace, override_get_session):
    # User 2 not in workspace
    u2 = User(name="Stranger", email="stranger@rec.com", password_hash="hash")
    db_session.add(u2)
    db_session.commit()
    db_session.refresh(u2)
    token = create_access_token(data={"sub": str(u2.id)})
    headers = {"Cookie": f"access_token={token}"}
    
    ws_id = test_workspace.id
    
    # GET list
    assert client.get(f"/api/v1/workspaces/{ws_id}/recurring", headers=headers).status_code == 403
    # POST
    assert client.post(f"/api/v1/workspaces/{ws_id}/recurring", json={"title":"X","base_amount":1,"day_of_month":1}, headers=headers).status_code == 403
    
    # Create an expense in the workspace to test specific resource access
    r1 = RecurringExpense(title="R1", base_amount=10, day_of_month=5, workspace_id=ws_id)
    db_session.add(r1)
    db_session.commit()
    db_session.refresh(r1)
    
    # GET one
    assert client.get(f"/api/v1/workspaces/{ws_id}/recurring/{r1.id}", headers=headers).status_code == 403
    # PUT
    assert client.put(f"/api/v1/workspaces/{ws_id}/recurring/{r1.id}", json={"title":"Y"}, headers=headers).status_code == 403
    # DELETE
    assert client.delete(f"/api/v1/workspaces/{ws_id}/recurring/{r1.id}", headers=headers).status_code == 403

def test_get_recurring_not_found(db_session: Session, auth_header, test_workspace, override_get_session):
    # Access valid workspace but invalid expense ID
    response = client.get(f"/api/v1/workspaces/{test_workspace.id}/recurring/9999", headers=auth_header)
    assert response.status_code == 404

def test_update_recurring_not_found(db_session: Session, auth_header, test_workspace, override_get_session):
    response = client.put(f"/api/v1/workspaces/{test_workspace.id}/recurring/9999", json={"title":"X"}, headers=auth_header)
    assert response.status_code == 404

def test_delete_recurring_not_found(db_session: Session, auth_header, test_workspace, override_get_session):
    response = client.delete(f"/api/v1/workspaces/{test_workspace.id}/recurring/9999", headers=auth_header)
    assert response.status_code == 404
