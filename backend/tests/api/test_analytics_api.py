import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session
from app.main import app
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.core.jwt import create_access_token

client = TestClient(app)

@pytest.fixture
def analytics_setup(db_session: Session):
    u = User(name="Analytic User", email="ana@example.com", password_hash="hash")
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    
    ws = Workspace(name="Analytic WS", created_by_user_id=u.id)
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)
    
    db_session.add(WorkspaceMembership(workspace_id=ws.id, user_id=u.id, role="owner"))
    db_session.commit()
    
    token = create_access_token(data={"sub": str(u.id)})
    headers = {"Cookie": f"access_token={token}"}
    
    return {"u": u, "ws": ws, "headers": headers}

def test_get_summary_variants(analytics_setup, override_get_session):
    ws_id = analytics_setup["ws"].id
    headers = analytics_setup["headers"]
    
    # 1. Without month
    response = client.get(f"/api/v1/workspaces/{ws_id}/analytics/summary", headers=headers)
    assert response.status_code == 200
    
    # 2. With month
    response = client.get(f"/api/v1/workspaces/{ws_id}/analytics/summary?month=2026-05", headers=headers)
    assert response.status_code == 200

def test_get_reports(analytics_setup, override_get_session):
    ws_id = analytics_setup["ws"].id
    headers = analytics_setup["headers"]
    
    response = client.get(f"/api/v1/workspaces/{ws_id}/analytics/reports", headers=headers)
    assert response.status_code == 200
    assert "monthly_history" in response.json()


def test_get_reports_com_mes(analytics_setup, override_get_session):
    """Relatórios seguem o período escolhido, como as outras telas."""
    ws_id = analytics_setup["ws"].id
    headers = analytics_setup["headers"]

    response = client.get(f"/api/v1/workspaces/{ws_id}/analytics/reports?month=2026-05", headers=headers)
    assert response.status_code == 200
    # A série de 6 meses termina no mês pedido
    assert [m["name"] for m in response.json()["monthly_history"]][-1] == "May"

    response = client.get(f"/api/v1/workspaces/{ws_id}/analytics/reports?month=xx", headers=headers)
    assert response.status_code == 400

def test_get_forecast_variants(analytics_setup, override_get_session):
    ws_id = analytics_setup["ws"].id
    headers = analytics_setup["headers"]
    
    # 1. Without month
    response = client.get(f"/api/v1/workspaces/{ws_id}/analytics/forecast", headers=headers)
    assert response.status_code == 200
    
    # 2. With valid month
    response = client.get(f"/api/v1/workspaces/{ws_id}/analytics/forecast?month=2026-12", headers=headers)
    assert response.status_code == 200
    
    # 3. With invalid month format (ValueError trigger)
    response = client.get(f"/api/v1/workspaces/{ws_id}/analytics/forecast?month=invalid", headers=headers)
    assert response.status_code == 400
    assert "Formato de mês inválido" in response.json()["error"]["message"]

def test_estimates_crud_and_variants(analytics_setup, override_get_session):
    ws_id = analytics_setup["ws"].id
    headers = analytics_setup["headers"]
    
    # Create
    payload = {"month": "2026-05", "category": "Food", "amount": 500.0}
    response = client.post(f"/api/v1/workspaces/{ws_id}/analytics/estimates", json=payload, headers=headers)
    assert response.status_code == 200
    assert response.json()["category"] == "Food"
    
    # List without filter
    response = client.get(f"/api/v1/workspaces/{ws_id}/analytics/estimates", headers=headers)
    assert len(response.json()) == 1
    
    # List with filter
    response = client.get(f"/api/v1/workspaces/{ws_id}/analytics/estimates?month=2026-05", headers=headers)
    assert len(response.json()) == 1
    
    response = client.get(f"/api/v1/workspaces/{ws_id}/analytics/estimates?month=2026-06", headers=headers)
    assert len(response.json()) == 0

def test_analytics_forbidden(db_session: Session, analytics_setup, override_get_session):
    # New user not in workspace
    u2 = User(name="Stranger", email="stranger@example.com", password_hash="hash")
    db_session.add(u2)
    db_session.commit()
    db_session.refresh(u2)
    
    token = create_access_token(data={"sub": str(u2.id)})
    headers = {"Cookie": f"access_token={token}"}
    ws_id = analytics_setup["ws"].id
    
    endpoints = [
        f"/api/v1/workspaces/{ws_id}/analytics/summary",
        f"/api/v1/workspaces/{ws_id}/analytics/reports",
        f"/api/v1/workspaces/{ws_id}/analytics/forecast",
        f"/api/v1/workspaces/{ws_id}/analytics/estimates",
    ]
    
    # GET tests
    for ep in endpoints:
        response = client.get(ep, headers=headers)
        assert response.status_code == 403

    # POST test for estimates
    payload = {"month": "2026-05", "category": "Food", "amount": 500.0}
    response = client.post(f"/api/v1/workspaces/{ws_id}/analytics/estimates", json=payload, headers=headers)
    assert response.status_code == 403
