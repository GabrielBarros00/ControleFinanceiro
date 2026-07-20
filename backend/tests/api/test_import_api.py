import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from sqlmodel import Session, select
from app.core.jwt import create_access_token
import io

client = TestClient(app)

@pytest.fixture
def auth_header(db_session: Session):
    user = User(name="Importer", email="import@example.com", password_hash="hash")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    
    token = create_access_token(data={"sub": str(user.id)})
    return {"Cookie": f"access_token={token}"}

@pytest.fixture
def test_workspace(db_session: Session, auth_header):
    user = db_session.exec(select(User).where(User.email == "import@example.com")).first()
    ws = Workspace(name="Import WS", created_by_user_id=user.id)
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)
    
    membership = WorkspaceMembership(workspace_id=ws.id, user_id=user.id, role="owner")
    db_session.add(membership)
    db_session.commit()
    
    return ws

def test_parse_csv_api(db_session: Session, auth_header, test_workspace, override_get_session):
    csv_content = "date,desc,amt\n2026-05-01,Lunch,15.50\n2026-05-02,Dinner,42.00"
    files = {"file": ("test.csv", io.BytesIO(csv_content.encode()), "text/csv")}
    data = {
        "date_column": "date",
        "description_column": "desc",
        "amount_column": "amt",
        "date_format": "%Y-%m-%d",
        "delimiter": ",",
        "decimal_separator": ".",
        "invert_amount": "false"
    }
    
    response = client.post(
        f"/api/v1/workspaces/{test_workspace.id}/imports/parse",
        files=files,
        data=data,
        headers=auth_header
    )
    
    assert response.status_code == 200
    payload = response.json()
    results = payload["rows"]
    assert payload["skipped"] == []
    assert len(results) == 2
    assert results[0]["title"] == "Lunch"
    assert float(results[0]["total_amount"]) == 15.5

def test_parse_csv_forbidden(db_session: Session, test_workspace, override_get_session):
    # Create another user
    u2 = User(name="User 2", email="u2@example.com", password_hash="hash")
    db_session.add(u2)
    db_session.commit()
    db_session.refresh(u2)
    
    t2 = create_access_token(data={"sub": str(u2.id)})
    headers2 = {"Cookie": f"access_token={t2}"}
    
    csv_content = "date,desc,amt\n2026-05-01,Lunch,15.50"
    files = {"file": ("test.csv", io.BytesIO(csv_content.encode()), "text/csv")}
    data = {"date_column": "date", "description_column": "desc", "amount_column": "amt"}
    
    response = client.post(
        f"/api/v1/workspaces/{test_workspace.id}/imports/parse",
        files=files,
        data=data,
        headers=headers2
    )
    assert response.status_code == 403

def test_parse_csv_forbidden_cross_workspace(db_session: Session, setup_data, override_get_session):
    # setup_data has u2 who is NOT in ws1
    ws1 = setup_data["ws1"]
    headers2 = setup_data["headers2"]
    
    csv_content = "date,desc,amt\n2026-05-01,Lunch,15.50"
    files = {"file": ("test.csv", io.BytesIO(csv_content.encode()), "text/csv")}
    data = {
        "date_column": "date",
        "description_column": "desc",
        "amount_column": "amt"
    }
    
    response = client.post(
        f"/api/v1/workspaces/{ws1.id}/imports/parse",
        files=files,
        data=data,
        headers=headers2
    )
    assert response.status_code == 403
