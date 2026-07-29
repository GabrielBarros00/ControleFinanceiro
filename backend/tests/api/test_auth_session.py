import pytest
from datetime import timedelta
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.core.security import get_password_hash, verify_password
from app.core.jwt import create_access_token, create_refresh_token, create_purpose_token
from app.core.config import settings
from app.models.user import User
from app.models.workspace import Workspace
from app.services.email_service import EmailService
from app.services.session_service import start_session
import app.api.routes.auth as auth_module

client = TestClient(app)


def _make_user(db: Session, email: str = "sess@example.com", password: str = "secret123") -> User:
    user = User(name="Sess", email=email, password_hash=get_password_hash(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# --- POST /auth/refresh ---

def test_refresh_success(db_session: Session, override_get_session):
    user = _make_user(db_session)
    # Sessão GERENCIADA (com jti/family), que é o único formato aceito
    refresh = start_session(db_session, user.id)
    db_session.commit()
    client.cookies.clear()
    client.cookies.set("refresh_token", refresh)

    res = client.post("/api/v1/auth/refresh")
    assert res.status_code == 200
    assert "access_token" in res.cookies
    assert "refresh_token" in res.cookies

    # O novo access token funciona
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 200


def test_refresh_recusa_formato_legado(db_session: Session, override_get_session):
    """Token sem jti/family (pré-SEC-004) não é mais aceito.

    Ele não tinha linha em RefreshSession, então `revoke_all_user_sessions` — a
    revogação usada na troca e na REDEFINIÇÃO de senha — não o alcançava: um
    token roubado continuava valendo depois de a vítima recuperar a conta.
    """
    user = _make_user(db_session, email="legado-refresh@example.com")
    client.cookies.clear()
    client.cookies.set("refresh_token", create_refresh_token({"sub": str(user.id)}))
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_refresh_requires_cookie(override_get_session):
    client.cookies.clear()
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_access_token_rejected_as_refresh(db_session: Session, override_get_session):
    user = _make_user(db_session, email="a2@example.com")
    client.cookies.clear()
    client.cookies.set("refresh_token", create_access_token({"sub": str(user.id)}))
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_refresh_token_rejected_as_access(db_session: Session, override_get_session):
    user = _make_user(db_session, email="a3@example.com")
    client.cookies.clear()
    client.cookies.set("access_token", create_refresh_token({"sub": str(user.id)}))
    assert client.get("/api/v1/auth/me").status_code == 401


# --- forgot-password / reset-password ---

def test_forgot_password_unknown_email_returns_200(db_session: Session, override_get_session):
    client.cookies.clear()
    res = client.post("/api/v1/auth/forgot-password", json={"email": "ghost@example.com"})
    assert res.status_code == 200


def test_full_password_reset_flow(db_session: Session, override_get_session, monkeypatch):
    user = _make_user(db_session, email="reset@example.com", password="oldpass1")
    captured = {}
    monkeypatch.setattr(
        EmailService, "send_password_reset",
        lambda to, link: captured.update({"to": to, "link": link})
    )
    client.cookies.clear()

    res = client.post("/api/v1/auth/forgot-password", json={"email": "reset@example.com"})
    assert res.status_code == 200
    assert captured["to"] == "reset@example.com"
    token = captured["link"].split("token=")[1]

    res = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "newpass1"})
    assert res.status_code == 200
    db_session.refresh(user)
    assert verify_password("newpass1", user.password_hash)

    # Token é de uso único: o fingerprint muda junto com o hash
    res = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "another1"})
    assert res.status_code == 400

    # Login com a senha nova funciona
    res = client.post("/api/v1/auth/login", json={"email": "reset@example.com", "password": "newpass1"})
    assert res.status_code == 200


def test_reset_password_invalid_token(override_get_session):
    client.cookies.clear()
    res = client.post("/api/v1/auth/reset-password", json={"token": "garbage", "new_password": "whatever1"})
    assert res.status_code == 400


def test_reset_password_rejects_other_token_types(db_session: Session, override_get_session):
    user = _make_user(db_session, email="purpose@example.com")
    client.cookies.clear()
    token = create_access_token({"sub": str(user.id)})
    res = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "whatever1"})
    assert res.status_code == 400


# --- change-password ---

def test_change_password_flow(db_session: Session, override_get_session):
    user = _make_user(db_session, email="chg@example.com", password="oldpass1")
    client.cookies.clear()
    client.cookies.set("access_token", create_access_token({"sub": str(user.id)}))

    # Senha atual errada → 400
    res = client.post("/api/v1/auth/change-password", json={
        "current_password": "errada", "new_password": "newpass1",
    })
    assert res.status_code == 400

    # Troca com sucesso
    res = client.post("/api/v1/auth/change-password", json={
        "current_password": "oldpass1", "new_password": "newpass1",
    })
    assert res.status_code == 200
    db_session.refresh(user)
    assert verify_password("newpass1", user.password_hash)


# --- Google OAuth ---

@pytest.fixture
def google_configured(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "csecret")
    monkeypatch.setattr(settings, "GOOGLE_REDIRECT_URI", "http://localhost:8000/api/v1/auth/google/callback")


def _oauth_state() -> str:
    """State válido + o cookie de nonce, como um navegador real faria.

    O callback só aceita o state se o nonce casar com o cookie `oauth_state`
    posto em /google/login — é o que impede login CSRF.
    """
    import secrets

    nonce = secrets.token_urlsafe(24)
    client.cookies.set("oauth_state", nonce)
    return create_purpose_token(
        {"nonce": nonce}, purpose="oauth_state", expires_delta=timedelta(minutes=10)
    )


def test_google_login_unconfigured(override_get_session, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", None)
    res = client.get("/api/v1/auth/google/login", follow_redirects=False)
    assert res.status_code == 503


def test_google_login_redirects_to_google(google_configured, override_get_session):
    res = client.get("/api/v1/auth/google/login", follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"].startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "state=" in res.headers["location"]
    # O nonce vai num cookie HttpOnly: é ele que amarra o callback a ESTE navegador
    assert "oauth_state" in res.cookies


def test_google_callback_sem_cookie_de_nonce_e_recusado(
    override_get_session, google_configured, monkeypatch
):
    """Login CSRF: state gerado pelo atacante não vale no navegador da vítima."""
    monkeypatch.setattr(
        auth_module, "_fetch_google_user",
        lambda code: {"email": "vitima@example.com", "name": "V", "email_verified": True}
    )
    state = create_purpose_token(
        {"nonce": "nonce-do-atacante"}, purpose="oauth_state", expires_delta=timedelta(minutes=10)
    )
    client.cookies.clear()  # navegador da vítima nunca passou por /google/login
    res = client.get(
        f"/api/v1/auth/google/callback?code=x&state={state}", follow_redirects=False
    )
    assert res.status_code == 307
    assert "error=google_state_invalido" in res.headers["location"]
    assert "access_token" not in res.cookies


def test_google_callback_conta_desativada_nao_loga(
    db_session: Session, override_get_session, google_configured, monkeypatch
):
    user = _make_user(db_session, email="off_google@example.com")
    user.is_active = False
    db_session.add(user)
    db_session.commit()

    monkeypatch.setattr(
        auth_module, "_fetch_google_user",
        lambda code: {"email": "off_google@example.com", "name": "X", "email_verified": True}
    )
    client.cookies.clear()
    res = client.get(
        f"/api/v1/auth/google/callback?code=x&state={_oauth_state()}", follow_redirects=False
    )
    assert res.status_code == 307
    assert "error=conta_desativada" in res.headers["location"]
    assert "access_token" not in res.cookies


def test_google_callback_creates_user_and_workspace(
    db_session: Session, override_get_session, google_configured, monkeypatch
):
    monkeypatch.setattr(
        auth_module, "_fetch_google_user",
        lambda code: {"email": "google@example.com", "name": "G User", "email_verified": True}
    )
    client.cookies.clear()
    res = client.get(
        f"/api/v1/auth/google/callback?code=x&state={_oauth_state()}",
        follow_redirects=False
    )
    assert res.status_code == 307
    assert "access_token" in res.cookies

    user = db_session.exec(select(User).where(User.email == "google@example.com")).first()
    assert user is not None
    assert user.password_hash == auth_module.OAUTH_PASSWORD_SENTINEL
    ws = db_session.exec(select(Workspace).where(Workspace.created_by_user_id == user.id)).first()
    assert ws is not None


def test_google_callback_existing_user_logs_in(
    db_session: Session, override_get_session, google_configured, monkeypatch
):
    _make_user(db_session, email="link@example.com")
    monkeypatch.setattr(
        auth_module, "_fetch_google_user",
        lambda code: {"email": "link@example.com", "name": "X"}
    )
    client.cookies.clear()
    res = client.get(
        f"/api/v1/auth/google/callback?code=x&state={_oauth_state()}",
        follow_redirects=False
    )
    assert res.status_code == 307
    assert "access_token" in res.cookies
    users = db_session.exec(select(User).where(User.email == "link@example.com")).all()
    assert len(users) == 1


def test_google_callback_accepts_pending_invites(
    db_session: Session, override_get_session, google_configured, monkeypatch
):
    """Conta nascida via Google NÃO entra sozinha no workspace do convite.

    O retorno do Google não carrega o token do convite, então não há como a
    pessoa ter consentido — e "o e-mail bate" nunca foi consentimento: quem
    soubesse o endereço de alguém colocava essa pessoa dentro das próprias
    finanças (e a si mesmo dentro das dela) sem ela aceitar nada. O convite vira
    NOTIFICAÇÃO, com aceite e recusa.
    """
    from datetime import timedelta as td
    from datetime import datetime as dt, UTC as utc
    from app.models.workspace import Workspace as WS, WorkspaceMembership as WM, WorkspaceInvite, WorkspaceRole

    host = _make_user(db_session, email="host@example.com")
    ws = WS(name="WS do Host", created_by_user_id=host.id)
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)
    db_session.add(WM(workspace_id=ws.id, user_id=host.id, role=WorkspaceRole.owner))
    db_session.add(WorkspaceInvite(
        workspace_id=ws.id,
        email="convidada@gmail.com",
        role=WorkspaceRole.member,
        invited_by_user_id=host.id,
        expires_at=dt.now(utc) + td(days=7),
    ))
    db_session.commit()

    monkeypatch.setattr(
        auth_module, "_fetch_google_user",
        lambda code: {"email": "convidada@gmail.com", "name": "Convidada", "email_verified": True}
    )
    client.cookies.clear()
    res = client.get(
        f"/api/v1/auth/google/callback?code=x&state={_oauth_state()}",
        follow_redirects=False
    )
    assert res.status_code == 307

    from app.models.notification import Notification

    new_user = db_session.exec(select(User).where(User.email == "convidada@gmail.com")).first()
    membership = db_session.exec(select(WM).where(
        WM.workspace_id == ws.id, WM.user_id == new_user.id
    )).first()
    assert membership is None, "entrou no workspace alheio só porque o e-mail batia"

    # O convite continua pendente e chega como aviso dentro do app
    aviso = db_session.exec(
        select(Notification).where(Notification.user_id == new_user.id)
    ).first()
    assert aviso is not None
    assert aviso.workspace_id == ws.id

    # Aceite explícito coloca a pessoa no workspace, com o papel do convite
    res = client.post(
        f"/api/v1/invites/accept/{aviso.invite_token}",
        headers={"Cookie": f"access_token={create_access_token({'sub': str(new_user.id)})}"},
    )
    assert res.status_code == 200, res.text
    membership = db_session.exec(select(WM).where(
        WM.workspace_id == ws.id, WM.user_id == new_user.id
    )).first()
    assert membership is not None
    assert membership.role == WorkspaceRole.member


def test_google_callback_bad_state(override_get_session, google_configured):
    client.cookies.clear()
    res = client.get("/api/v1/auth/google/callback?code=x&state=bad", follow_redirects=False)
    assert res.status_code == 307
    assert "error=google_state_invalido" in res.headers["location"]


def test_login_oauth_only_account_gets_clear_error(db_session: Session, override_get_session):
    user = User(name="OAuth", email="oauthonly@example.com", password_hash=auth_module.OAUTH_PASSWORD_SENTINEL)
    db_session.add(user)
    db_session.commit()
    client.cookies.clear()
    res = client.post("/api/v1/auth/login", json={"email": "oauthonly@example.com", "password": "whatever"})
    assert res.status_code == 401
    assert "Google" in res.json()["error"]["message"]
