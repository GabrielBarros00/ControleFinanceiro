"""Regressão: trocar/redefinir senha derruba as sessões e conta desativada não loga.

Antes destas correções o refresh token continuava valendo os 7 dias inteiros
depois da vítima trocar a senha (o ADR 0013 só cobria o logout), e o login
devolvia 200 + cookies para conta desativada — só as requisições SEGUINTES é
que davam 401.
"""
from datetime import datetime, timedelta, UTC

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.routes.auth import _password_fingerprint
from app.core.jwt import create_purpose_token
from app.core.security import get_password_hash
from app.main import app
from app.models.refresh_session import RefreshSession
from app.models.user import User

SENHA = "senha-antiga-123"


@pytest.fixture(name="client")
def client_fixture(override_get_session):
    return TestClient(app)


def _user(db: Session, email: str, **kwargs) -> User:
    user = User(name="Fulana", email=email, password_hash=get_password_hash(SENHA), **kwargs)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _login(client: TestClient, email: str) -> str:
    res = client.post("/api/v1/auth/login", json={"email": email, "password": SENHA})
    assert res.status_code == 200, res.text
    return client.cookies["refresh_token"]


def _refresh_com(token: str) -> int:
    outro = TestClient(app)
    outro.cookies.set("refresh_token", token)
    return outro.post("/api/v1/auth/refresh").status_code


# --- Conta desativada / excluída ------------------------------------------


def test_login_recusa_conta_desativada(client, db_session):
    _user(db_session, "inativa@example.com", is_active=False)
    res = client.post("/api/v1/auth/login", json={"email": "inativa@example.com", "password": SENHA})
    assert res.status_code == 401
    assert "access_token" not in res.cookies


def test_login_recusa_conta_excluida(client, db_session):
    _user(db_session, "excluida@example.com", deleted_at=datetime.now(UTC))
    res = client.post("/api/v1/auth/login", json={"email": "excluida@example.com", "password": SENHA})
    assert res.status_code == 401
    assert "access_token" not in res.cookies


def test_login_normal_continua_funcionando(client, db_session):
    _user(db_session, "ativa@example.com")
    res = client.post("/api/v1/auth/login", json={"email": "ativa@example.com", "password": SENHA})
    assert res.status_code == 200
    assert "access_token" in res.cookies


# --- Revogação de sessões -------------------------------------------------


def test_change_password_revoga_sessoes_antigas(client, db_session):
    _user(db_session, "troca@example.com")

    # Sessão de outro dispositivo (o "ladrão")
    ladrao = TestClient(app)
    ladrao.post("/api/v1/auth/login", json={"email": "troca@example.com", "password": SENHA})
    token_ladrao = ladrao.cookies["refresh_token"]

    _login(client, "troca@example.com")
    res = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": SENHA, "new_password": "senha-nova-456"},
    )
    assert res.status_code == 200

    assert _refresh_com(token_ladrao) == 401


def test_change_password_mantem_quem_trocou_logado(client, db_session):
    _user(db_session, "mantem@example.com")
    _login(client, "mantem@example.com")

    res = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": SENHA, "new_password": "senha-nova-456"},
    )
    assert res.status_code == 200
    # Cookies reemitidos: quem trocou a senha segue navegando sem novo login
    assert "refresh_token" in res.cookies
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.post("/api/v1/auth/refresh").status_code == 200


def test_reset_password_revoga_sessoes(client, db_session):
    user = _user(db_session, "reset@example.com")

    ladrao = TestClient(app)
    ladrao.post("/api/v1/auth/login", json={"email": "reset@example.com", "password": SENHA})
    token_ladrao = ladrao.cookies["refresh_token"]

    token = create_purpose_token(
        {"sub": str(user.id), "pwf": _password_fingerprint(user.password_hash)},
        purpose="password_reset",
        expires_delta=timedelta(minutes=30),
    )
    res = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "new_password": "senha-nova-456"}
    )
    assert res.status_code == 200

    assert _refresh_com(token_ladrao) == 401
    vivas = db_session.exec(
        select(RefreshSession).where(
            RefreshSession.user_id == user.id, RefreshSession.revoked_at.is_(None)
        )
    ).all()
    assert vivas == []
