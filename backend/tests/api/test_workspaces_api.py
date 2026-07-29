import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from app.main import app
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.core.jwt import create_access_token

client = TestClient(app)

@pytest.fixture
def test_users(db_session: Session):
    u1 = User(name="User 1", email="u1@example.com", password_hash="hash")
    u2 = User(name="User 2", email="u2@example.com", password_hash="hash")
    db_session.add_all([u1, u2])
    db_session.commit()
    db_session.refresh(u1)
    db_session.refresh(u2)
    return u1, u2

@pytest.fixture
def auth_headers(test_users):
    u1, u2 = test_users
    token1 = create_access_token(data={"sub": str(u1.id)})
    token2 = create_access_token(data={"sub": str(u2.id)})
    return {
        "u1": {"Cookie": f"access_token={token1}"},
        "u2": {"Cookie": f"access_token={token2}"}
    }

def test_create_workspace(db_session: Session, auth_headers, override_get_session):
    payload = {"name": "New Workspace", "description": "Desc"}
    response = client.post("/api/v1/workspaces/", json=payload, headers=auth_headers["u1"])

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "New Workspace"

    # O criador vira owner do workspace
    workspace_id = data["id"]
    membership = db_session.exec(
        select(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace_id)
    ).first()
    assert membership is not None
    assert membership.user_id is not None
    assert membership.role == WorkspaceRole.owner

def test_create_workspace_com_moeda_base(db_session: Session, auth_headers, override_get_session):
    """Dá para nascer em outra moeda. Antes só existia o PUT, que reconverte TODO
    o histórico — uma operação pesada e sujeita a MissingRates para um workspace
    ainda vazio."""
    response = client.post(
        "/api/v1/workspaces/",
        json={"name": "Viagem", "base_currency": "usd"},
        headers=auth_headers["u1"],
    )
    assert response.status_code == 200, response.text
    # Normalizado na borda (OptionalCurrencyCode)
    assert response.json()["base_currency"] == "USD"


def test_create_workspace_recusa_moeda_invalida(auth_headers, override_get_session):
    response = client.post(
        "/api/v1/workspaces/",
        json={"name": "X", "base_currency": "NOTACURRENCY"},
        headers=auth_headers["u1"],
    )
    assert response.status_code == 422, response.text


def test_list_workspaces_ordenado_por_id(db_session: Session, auth_headers, override_get_session):
    """Sem ORDER BY o banco devolvia na ordem que quisesse — e o cliente escolhe o
    workspace ativo como `workspaces[0]`."""
    for nome in ("A", "B", "C"):
        assert client.post(
            "/api/v1/workspaces/", json={"name": nome}, headers=auth_headers["u1"]
        ).status_code == 200

    listagem = client.get("/api/v1/workspaces/", headers=auth_headers["u1"])
    assert listagem.status_code == 200
    ids = [w["id"] for w in listagem.json()]
    assert ids == sorted(ids)


def test_list_workspaces_isolation(db_session: Session, test_users, auth_headers, override_get_session):
    u1, u2 = test_users

    # WS1 for User 1
    ws1 = Workspace(name="WS1", created_by_user_id=u1.id)
    db_session.add(ws1)
    db_session.commit()
    db_session.refresh(ws1)
    db_session.add(WorkspaceMembership(workspace_id=ws1.id, user_id=u1.id, role="owner"))

    # WS2 for User 2
    ws2 = Workspace(name="WS2", created_by_user_id=u2.id)
    db_session.add(ws2)
    db_session.commit()
    db_session.refresh(ws2)
    db_session.add(WorkspaceMembership(workspace_id=ws2.id, user_id=u2.id, role="owner"))

    db_session.commit()

    # User 1 should only see WS1
    response = client.get("/api/v1/workspaces/", headers=auth_headers["u1"])
    assert response.status_code == 200
    data = response.json()

    ws_names = [w["name"] for w in data]
    assert "WS1" in ws_names
    assert "WS2" not in ws_names

def test_get_workspace_access_control(db_session: Session, test_users, auth_headers, override_get_session):
    u1, u2 = test_users

    ws1 = Workspace(name="WS-SECURE", created_by_user_id=u1.id)
    db_session.add(ws1)
    db_session.commit()
    db_session.refresh(ws1)
    db_session.add(WorkspaceMembership(workspace_id=ws1.id, user_id=u1.id, role="owner"))
    db_session.commit()

    # User 1 can access WS1
    response = client.get(f"/api/v1/workspaces/{ws1.id}", headers=auth_headers["u1"])
    assert response.status_code == 200
    assert response.json()["name"] == "WS-SECURE"

    # User 2 CANNOT access WS1 (403 Forbidden)
    response = client.get(f"/api/v1/workspaces/{ws1.id}", headers=auth_headers["u2"])
    assert response.status_code == 403
    assert response.json()["error"]["message"] == "Você não é membro deste workspace"

def test_get_workspace_deleted_but_member(db_session: Session, test_users, auth_headers, override_get_session):
    from datetime import datetime, UTC
    u1, _ = test_users
    # Workspace soft-deletado: membership existe, mas o acesso responde 404
    ws = Workspace(name="Apagado", created_by_user_id=u1.id, deleted_at=datetime.now(UTC))
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)
    db_session.add(WorkspaceMembership(workspace_id=ws.id, user_id=u1.id, role="owner"))
    db_session.commit()

    response = client.get(f"/api/v1/workspaces/{ws.id}", headers=auth_headers["u1"])
    assert response.status_code == 404

def test_get_workspace_not_found(db_session: Session, test_users, auth_headers, override_get_session):
    u1, _ = test_users
    # Workspace inexistente responde 404 (independente de membership)
    response = client.get("/api/v1/workspaces/9999", headers=auth_headers["u1"])
    assert response.status_code == 404
