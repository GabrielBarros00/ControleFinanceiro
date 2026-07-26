"""E-mail sempre em caixa baixa (B4).

`User.email` é unique na string crua: sem normalizar, `Joao@x.com` e
`joao@x.com` viravam DUAS contas, e o convite/reset de uma não valia para a
outra. A normalização é feita na entrada, num ponto só.
"""
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceInvite, WorkspaceMembership, WorkspaceRole
from app.core.jwt import create_access_token
from datetime import datetime, timedelta, UTC


def test_registro_normaliza_o_email(db_session: Session, override_get_session):
    with TestClient(app) as client:
        r = client.post("/api/v1/auth/register", json={
            "name": "Gabriel", "email": "  Gabriel@Example.COM  ", "password": "segredo123",
        })
    assert r.status_code == 200
    assert r.json()["email"] == "gabriel@example.com"

    user = db_session.exec(select(User)).one()
    assert user.email == "gabriel@example.com"


def test_email_duplicado_so_pela_caixa_e_recusado(db_session: Session, override_get_session):
    with TestClient(app) as client:
        primeiro = client.post("/api/v1/auth/register", json={
            "name": "A", "email": "dup@example.com", "password": "segredo123",
        })
        assert primeiro.status_code == 200
        segundo = client.post("/api/v1/auth/register", json={
            "name": "B", "email": "DUP@Example.com", "password": "segredo123",
        })
    assert segundo.status_code == 400


def test_login_aceita_qualquer_caixa(db_session: Session, override_get_session):
    with TestClient(app) as client:
        client.post("/api/v1/auth/register", json={
            "name": "Gabriel", "email": "login@example.com", "password": "segredo123",
        })
        r = client.post("/api/v1/auth/login", json={
            "email": "LOGIN@Example.COM", "password": "segredo123",
        })
    assert r.status_code == 200


def test_convite_casa_independente_da_caixa(db_session: Session, override_get_session):
    """O caso que quebrava: convite gravado com uma grafia, usuário com outra."""
    dono = User(name="Dono", email="dono@example.com", password_hash="h")
    convidado = User(name="Convidado", email="convidado@example.com", password_hash="h")
    ws = Workspace(name="WS")
    db_session.add_all([dono, convidado, ws])
    db_session.flush()
    db_session.add(WorkspaceMembership(
        workspace_id=ws.id, user_id=dono.id, role=WorkspaceRole.owner
    ))
    invite = WorkspaceInvite(
        workspace_id=ws.id, email="convidado@example.com", role=WorkspaceRole.member,
        invited_by_user_id=dono.id, expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db_session.add(invite)
    db_session.commit()

    token = create_access_token({"sub": str(convidado.id)})
    with TestClient(app) as client:
        r = client.post(
            f"/api/v1/invites/accept/{invite.token}",
            headers={"Cookie": f"access_token={token}"},
        )
    assert r.status_code == 200


def test_convite_por_email_normaliza(db_session: Session, override_get_session):
    dono = User(name="Dono", email="dono2@example.com", password_hash="h")
    ws = Workspace(name="WS2")
    db_session.add_all([dono, ws])
    db_session.flush()
    db_session.add(WorkspaceMembership(
        workspace_id=ws.id, user_id=dono.id, role=WorkspaceRole.owner
    ))
    db_session.commit()

    token = create_access_token({"sub": str(dono.id)})
    with TestClient(app) as client:
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/invites",
            json={"email": "Novo@Example.COM", "role": "member"},
            headers={"Cookie": f"access_token={token}"},
        )
    assert r.status_code == 200

    invite = db_session.exec(select(WorkspaceInvite)).one()
    assert invite.email == "novo@example.com"
