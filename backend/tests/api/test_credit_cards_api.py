import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session
from app.main import app
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.models.credit_card import CreditCard
from app.core.jwt import create_access_token

client = TestClient(app)

@pytest.fixture
def setup_data(db_session: Session):
    # Users
    u1 = User(name="User 1", email="u1@example.com", password_hash="hash")
    u2 = User(name="User 2", email="u2@example.com", password_hash="hash")
    db_session.add_all([u1, u2])
    db_session.commit()
    db_session.refresh(u1)
    db_session.refresh(u2)
    
    # Workspaces
    ws1 = Workspace(name="WS1", created_by_user_id=u1.id)
    ws2 = Workspace(name="WS2", created_by_user_id=u2.id)
    db_session.add_all([ws1, ws2])
    db_session.commit()
    db_session.refresh(ws1)
    db_session.refresh(ws2)
    
    # Memberships
    db_session.add(WorkspaceMembership(workspace_id=ws1.id, user_id=u1.id, role="owner"))
    db_session.add(WorkspaceMembership(workspace_id=ws2.id, user_id=u2.id, role="owner"))
    db_session.commit()
    
    # Tokens
    t1 = create_access_token(data={"sub": str(u1.id)})
    t2 = create_access_token(data={"sub": str(u2.id)})
    
    return {
        "u1": u1, "u2": u2,
        "ws1": ws1, "ws2": ws2,
        "headers1": {"Cookie": f"access_token={t1}"},
        "headers2": {"Cookie": f"access_token={t2}"}
    }

def test_create_credit_card(setup_data, override_get_session):
    setup_data["ws1"]
    
    payload = {
        "name": "Nubank",
        "limit": 5000.0,
        "closing_day": 5,
        "due_day": 15
    }
    
    response = client.post("/api/v1/me/credit-cards/", json=payload, headers=setup_data["headers1"])
    assert response.status_code == 200
    assert response.json()["name"] == "Nubank"
    assert float(response.json()["limit"]) == 5000.0

def test_list_credit_cards_isolation(db_session: Session, setup_data, override_get_session):
    """O isolamento é por DONO, não por workspace (ADR 0021)."""
    # Cartão do u1
    c1 = CreditCard(name="Card 1", limit=1000, closing_day=1, due_day=10,
                    owner_user_id=setup_data["u1"].id)
    # Cartão do u2
    c2 = CreditCard(name="Card 2", limit=2000, closing_day=1, due_day=10,
                    owner_user_id=setup_data["u2"].id)
    db_session.add_all([c1, c2])
    db_session.commit()

    # User 1 should only see Card 1
    response = client.get("/api/v1/me/credit-cards/", headers=setup_data["headers1"])
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Card 1"

def test_cartao_criado_pertence_a_quem_criou(setup_data, override_get_session):
    """Rota pessoal não tem "proibido" (ADR 0021): ela cria o cartão DE QUEM PEDE.

    Antes o gate era o workspace da URL e um não-membro levava 403. Agora o
    isolamento é que o cartão nasce do criador e nunca aparece para outro.
    """
    payload = {"name": "Meu cartão", "limit": 100, "closing_day": 1, "due_day": 2}
    response = client.post("/api/v1/me/credit-cards/", json=payload, headers=setup_data["headers1"])
    assert response.status_code == 200
    assert response.json()["owner_user_id"] == setup_data["u1"].id

    do_u2 = client.get("/api/v1/me/credit-cards/", headers=setup_data["headers2"]).json()
    assert response.json()["id"] not in [c["id"] for c in do_u2]
