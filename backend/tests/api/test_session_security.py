"""Sessões de refresh persistidas (SEC-004) e headers de segurança (SEC-006)."""
from datetime import datetime, timedelta, UTC

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.core.jwt import decode_token
from app.core.security import get_password_hash
from app.models.refresh_session import RefreshSession
from app.models.user import User
from app.services.session_service import JANELA_DE_REAPRESENTACAO

client = TestClient(app)


def _login(db: Session, email="rot@example.com", password="secret123"):
    db.add(User(name="Rot", email=email, password_hash=get_password_hash(password)))
    db.commit()
    client.cookies.clear()
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def _refresh(token: str):
    client.cookies.clear()
    return client.post("/api/v1/auth/refresh", headers={"Cookie": f"refresh_token={token}"})


def _jti(token: str) -> str:
    return decode_token(token)["jti"]


def _envelhecer_rotacao(db: Session, token: str) -> None:
    """Leva a rotação de `token` para ANTES da janela de reapresentação."""
    sessao = db.exec(select(RefreshSession).where(RefreshSession.jti == _jti(token))).one()
    sessao.revoked_at = datetime.now(UTC) - JANELA_DE_REAPRESENTACAO - timedelta(seconds=1)
    db.add(sessao)
    db.commit()


def test_refresh_rotaciona_e_reuso_revoga_familia(db_session, override_get_session):
    res = _login(db_session)
    r1 = res.cookies.get("refresh_token")
    assert r1

    res = _refresh(r1)
    assert res.status_code == 200
    r2 = res.cookies.get("refresh_token")
    assert r2 and r2 != r1  # rotacionou

    # Reapresentar o token já rotacionado, passada a janela → reuso detectado
    _envelhecer_rotacao(db_session, r1)
    assert _refresh(r1).status_code == 401
    # A família inteira caiu: o token vigente (r2) também morre
    assert _refresh(r2).status_code == 401


def test_reapresentar_logo_depois_da_rotacao_devolve_a_sessao_vigente(db_session, override_get_session):
    """A pessoa chegando atrasada não é ladrão (ADR 0042).

    Medido antes da mudança: duas renovações com o mesmo cookie — a aba e o
    WebSocket na volta do celular — terminavam com uma 401 e a família revogada,
    e a pessoa era deslogada na renovação seguinte. O mesmo acontecia quando a
    resposta da renovação se perdia na rede: o servidor girava, o navegador
    ficava com o cookie velho.
    """
    r1 = _login(db_session, email="janela@example.com").cookies.get("refresh_token")

    res = _refresh(r1)
    assert res.status_code == 200
    r2 = res.cookies.get("refresh_token")

    res = _refresh(r1)  # a segunda renovação, com o cookie de antes
    assert res.status_code == 200
    assert "access_token" in res.cookies
    r2_de_novo = res.cookies.get("refresh_token")
    # A MESMA sessão vigente, e não uma segunda: a cadeia não se ramifica
    assert _jti(r2_de_novo) == _jti(r2)

    # E nada foi revogado: os dois cookies seguem a cadeia normalmente
    assert _refresh(r2_de_novo).status_code == 200
    vivas = db_session.exec(
        select(RefreshSession).where(
            RefreshSession.family_id == decode_token(r1)["family"],
            RefreshSession.revoked_at.is_(None),
        )
    ).all()
    assert len(vivas) == 1


def test_sessao_encerrada_nao_volta_pela_janela(db_session, override_get_session):
    """Logout dentro da janela: o token girado há pouco NÃO ressuscita a sessão.

    A janela só vale enquanto a sucessora está viva — o logout (e a troca de
    senha) revoga sem criar sucessora, e o token de antes cai no reuso de sempre.
    """
    r1 = _login(db_session, email="janela-logout@example.com").cookies.get("refresh_token")
    r2 = _refresh(r1).cookies.get("refresh_token")

    client.cookies.clear()
    client.post("/api/v1/auth/logout", headers={"Cookie": f"refresh_token={r2}"})

    assert _refresh(r1).status_code == 401
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
