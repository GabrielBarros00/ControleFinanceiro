from fastapi.testclient import TestClient
from app.main import app
from app.core.security import get_password_hash
from app.models.user import User
from app.models.income import Income
from app.models.credit_card import CreditCard
from app.models.workspace import Workspace
from sqlmodel import Session, select
from app.core.jwt import create_access_token

client = TestClient(app)

def test_register_user_success(db_session: Session, override_get_session):
    register_data = {
        "name": "New User",
        "email": "new@example.com",
        "password": "strongpassword"
    }
    response = client.post("/api/v1/auth/register", json=register_data)
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "new@example.com"
    assert "id" in data
    
    # Verify user in DB
    user = db_session.exec(select(User).where(User.email == "new@example.com")).first()
    assert user is not None
    assert user.name == "New User"
    
    # Verify default workspace created
    workspace = db_session.exec(select(Workspace).where(Workspace.created_by_user_id == user.id)).first()
    assert workspace is not None
    assert workspace.name == "Meu Workspace"

def test_register_user_duplicate_email(db_session: Session, override_get_session):
    # Setup existing user
    user = User(name="Existing", email="existing@example.com", password_hash="hash")
    db_session.add(user)
    db_session.commit()
    
    register_data = {
        "name": "Another",
        "email": "existing@example.com",
        "password": "password"
    }
    response = client.post("/api/v1/auth/register", json=register_data)
    assert response.status_code == 400
    assert response.json()["error"]["message"] == "Este email já está cadastrado"

def test_login_success(db_session: Session, override_get_session):
    hashed_password = get_password_hash("testpass")
    user = User(name="Test User", email="test@example.com", password_hash=hashed_password)
    db_session.add(user)
    db_session.commit()
    
    response = client.post("/api/v1/auth/login", json={"email": "test@example.com", "password": "testpass"})
    assert response.status_code == 200
    assert "access_token" in response.cookies
    assert "refresh_token" in response.cookies

def test_login_failure(db_session: Session, override_get_session):
    response = client.post("/api/v1/auth/login", json={"email": "nonexistent@example.com", "password": "wrong"})
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Email ou senha incorretos"

def test_get_me_success(db_session: Session, override_get_session):
    user = User(name="Me", email="me@example.com", password_hash="hash")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    
    token = create_access_token(data={"sub": str(user.id)})
    client.cookies.set("access_token", token)
    
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == "me@example.com"

def test_get_me_unauthorized(override_get_session):
    client.cookies.clear()
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"

def test_get_me_invalid_token_missing_sub(override_get_session):
    # Payload sem "sub"
    token = create_access_token(data={})
    client.cookies.set("access_token", token)
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Token inválido ou expirado"

def test_get_me_user_not_found(override_get_session):
    # Token para user que não existe (ID 9999)
    token = create_access_token(data={"sub": "9999"})
    client.cookies.set("access_token", token)
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Usuário não encontrado"

def test_logout(override_get_session):
    client.cookies.set("access_token", "some-token")
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 200
    # access_token cookie is deleted (max-age=0)
    assert response.cookies.get("access_token") in [None, ""]

def test_finish_onboarding_success(db_session: Session, override_get_session):
    user = User(name="Onboard Me", email="onboard@example.com", password_hash="hash", needs_onboarding=True)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    
    token = create_access_token(data={"sub": str(user.id)})
    client.cookies.set("access_token", token)
    
    # Create a workspace (com membership — onboarding valida acesso)
    from app.models.workspace import WorkspaceMembership
    ws = Workspace(name="Test WS", created_by_user_id=user.id)
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)
    db_session.add(WorkspaceMembership(workspace_id=ws.id, user_id=user.id, role="owner"))
    db_session.commit()

    onboarding_data = {
        "workspace_id": ws.id,
        "salary": 5000.50,
        "credit_card_name": "Nubank",
        "credit_card_limit": 2000.00,
        "credit_card_closing_day": 10
    }
    
    response = client.post("/api/v1/auth/onboarding", json=onboarding_data)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    
    # Verify side effects
    db_session.refresh(user)
    assert user.needs_onboarding is False
    
    income = db_session.exec(select(Income).where(Income.user_id == user.id)).first()
    assert income is not None
    assert income.amount == 5000.50
    
    card = db_session.exec(select(CreditCard).where(CreditCard.owner_user_id == user.id)).first()
    assert card is not None
    assert card.name == "Nubank"
    assert card.limit == 2000.00
    assert card.closing_day == 10
    assert card.due_day == 20 # (10 + 10) % 31

def test_finish_onboarding_minimal(db_session: Session, override_get_session):
    from app.models.workspace import WorkspaceMembership

    user = User(name="Onboard Minimal", email="minimal@example.com", password_hash="hash", needs_onboarding=True)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    ws = Workspace(name="Minimal WS", created_by_user_id=user.id)
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)
    db_session.add(WorkspaceMembership(workspace_id=ws.id, user_id=user.id, role="owner"))
    db_session.commit()

    token = create_access_token(data={"sub": str(user.id)})
    client.cookies.set("access_token", token)

    onboarding_data = {
        "workspace_id": ws.id,
        "salary": 3000
    }

    response = client.post("/api/v1/auth/onboarding", json=onboarding_data)
    assert response.status_code == 200

    # Verify no card created
    card = db_session.exec(select(CreditCard).where(CreditCard.owner_user_id == user.id)).first()
    assert card is None


def test_finish_onboarding_foreign_workspace_forbidden(db_session: Session, override_get_session):
    """Onboarding em workspace do qual não sou membro é rejeitado (anti-IDOR)."""
    from app.models.workspace import WorkspaceMembership

    victim = User(name="Vitima", email="vitima@example.com", password_hash="hash")
    attacker = User(name="Atacante", email="atacante@example.com", password_hash="hash", needs_onboarding=True)
    db_session.add_all([victim, attacker])
    db_session.commit()
    db_session.refresh(victim)
    db_session.refresh(attacker)

    ws = Workspace(name="WS da Vitima", created_by_user_id=victim.id)
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)
    db_session.add(WorkspaceMembership(workspace_id=ws.id, user_id=victim.id, role="owner"))
    db_session.commit()

    token = create_access_token(data={"sub": str(attacker.id)})
    client.cookies.set("access_token", token)

    response = client.post("/api/v1/auth/onboarding", json={"workspace_id": ws.id, "salary": 1})
    assert response.status_code == 403
