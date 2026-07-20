"""Sessões de refresh persistidas (SEC-004) e headers de segurança (SEC-006)."""
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import app
from app.core.security import get_password_hash
from app.models.user import User

client = TestClient(app)


def _login(db: Session, email="rot@example.com", password="secret123"):
    db.add(User(name="Rot", email=email, password_hash=get_password_hash(password)))
    db.commit()
    client.cookies.clear()
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def _refresh(token: str):
    client.cookies.clear()
    return client.post("/api/v1/auth/refresh", headers={"Cookie": f"refresh_token={token}"})


def test_refresh_rotaciona_e_reuso_revoga_familia(db_session, override_get_session):
    res = _login(db_session)
    r1 = res.cookies.get("refresh_token")
    assert r1

    res = _refresh(r1)
    assert res.status_code == 200
    r2 = res.cookies.get("refresh_token")
    assert r2 and r2 != r1  # rotacionou

    # Reapresentar o token já rotacionado → reuso detectado
    assert _refresh(r1).status_code == 401
    # A família inteira caiu: o token vigente (r2) também morre
    assert _refresh(r2).status_code == 401


def test_logout_revoga_refresh(db_session, override_get_session):
    res = _login(db_session, email="logout@example.com")
    r1 = res.cookies.get("refresh_token")
    client.cookies.clear()
    client.post("/api/v1/auth/logout", headers={"Cookie": f"refresh_token={r1}"})
    # Token copiado deixa de valer após o logout
    assert _refresh(r1).status_code == 401


def test_headers_de_seguranca(override_get_session):
    res = client.get("/api/v1/health")
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("X-Frame-Options") == "DENY"
    assert "Permissions-Policy" in res.headers
