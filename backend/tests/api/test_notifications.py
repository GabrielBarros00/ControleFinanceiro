"""Notificações e consentimento no convite (E15)."""
from datetime import datetime, timedelta, UTC

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.jwt import create_access_token
from app.main import app
from app.models.notification import Notification
from app.models.user import User
from app.models.workspace import (
    Workspace,
    WorkspaceInvite,
    WorkspaceMembership,
    WorkspaceRole,
)

client = TestClient(app)


def _headers(user: User) -> dict:
    return {"Cookie": "access_token=" + create_access_token({"sub": str(user.id)})}


@pytest.fixture
def cena(db_session: Session, override_get_session):
    dono = User(name="Dono", email="dono@n.com", password_hash="h")
    convidado = User(name="Convidado", email="convidado@n.com", password_hash="h")
    estranho = User(name="Estranho", email="estranho@n.com", password_hash="h")
    ws = Workspace(name="Casa")
    db_session.add_all([dono, convidado, estranho, ws])
    db_session.flush()
    db_session.add(WorkspaceMembership(
        workspace_id=ws.id, user_id=dono.id, role=WorkspaceRole.owner
    ))
    db_session.commit()
    return {"dono": dono, "convidado": convidado, "estranho": estranho, "ws": ws, "db": db_session}


def _convidar(cena) -> str:
    resposta = client.post(
        f"/api/v1/workspaces/{cena['ws'].id}/invites",
        json={"email": "convidado@n.com", "role": "member"},
        headers=_headers(cena["dono"]),
    )
    assert resposta.status_code == 200
    token = cena["db"].exec(select(WorkspaceInvite)).one().token
    return token


def test_convite_gera_notificacao_nao_lida(cena):
    _convidar(cena)
    resposta = client.get("/api/v1/notifications", headers=_headers(cena["convidado"]))
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["unread"] == 1
    assert corpo["items"][0]["type"] == "workspace_invite"
    assert corpo["items"][0]["workspace_name"] == "Casa"
    assert corpo["items"][0]["invite_token"]


def test_notificacao_e_pessoal(cena):
    """Notificação não tem workspace para o require_role proteger — o gate é o
    user_id, e ele precisa segurar."""
    _convidar(cena)
    resposta = client.get("/api/v1/notifications", headers=_headers(cena["estranho"]))
    assert resposta.status_code == 200
    assert resposta.json()["items"] == []
    assert resposta.json()["unread"] == 0


def test_aceitar_convite_entra_e_zera_o_aviso(cena):
    token = _convidar(cena)
    resposta = client.post(
        f"/api/v1/invites/accept/{token}", headers=_headers(cena["convidado"])
    )
    assert resposta.status_code == 200

    membro = cena["db"].exec(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == cena["ws"].id,
            WorkspaceMembership.user_id == cena["convidado"].id,
        )
    ).first()
    assert membro is not None

    # O aviso cumpriu o papel: sem isto o contador nunca zerava
    depois = client.get("/api/v1/notifications", headers=_headers(cena["convidado"]))
    assert depois.json()["unread"] == 0


def test_recusar_convite_nao_entra_e_zera_o_aviso(cena):
    """Sem recusar, a única saída para o convite era aceitá-lo."""
    token = _convidar(cena)
    resposta = client.post(
        f"/api/v1/invites/decline/{token}", headers=_headers(cena["convidado"])
    )
    assert resposta.status_code == 200

    membro = cena["db"].exec(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == cena["ws"].id,
            WorkspaceMembership.user_id == cena["convidado"].id,
        )
    ).first()
    assert membro is None

    depois = client.get("/api/v1/notifications", headers=_headers(cena["convidado"]))
    assert depois.json()["unread"] == 0

    # E o convite recusado não pode mais ser aceito
    retry = client.post(
        f"/api/v1/invites/accept/{token}", headers=_headers(cena["convidado"])
    )
    assert retry.status_code == 404


def test_recusar_convite_de_outro_email_e_recusado(cena):
    token = _convidar(cena)
    resposta = client.post(
        f"/api/v1/invites/decline/{token}", headers=_headers(cena["estranho"])
    )
    assert resposta.status_code == 403


def test_marcar_como_lida(cena):
    _convidar(cena)
    aviso = cena["db"].exec(select(Notification)).one()

    resposta = client.post(
        f"/api/v1/notifications/{aviso.id}/read", headers=_headers(cena["convidado"])
    )
    assert resposta.status_code == 200
    assert resposta.json()["read_at"] is not None

    lista = client.get("/api/v1/notifications", headers=_headers(cena["convidado"]))
    assert lista.json()["unread"] == 0


def test_nao_marca_notificacao_alheia(cena):
    _convidar(cena)
    aviso = cena["db"].exec(select(Notification)).one()
    resposta = client.post(
        f"/api/v1/notifications/{aviso.id}/read", headers=_headers(cena["estranho"])
    )
    assert resposta.status_code == 404


def test_marcar_todas_como_lidas(cena):
    db = cena["db"]
    for i in range(3):
        db.add(Notification(
            user_id=cena["convidado"].id, type="member_added",
            title=f"Aviso {i}",
        ))
    db.commit()

    resposta = client.post("/api/v1/notifications/read-all", headers=_headers(cena["convidado"]))
    assert resposta.status_code == 200
    assert resposta.json()["marked"] == 3
    lista = client.get("/api/v1/notifications", headers=_headers(cena["convidado"]))
    assert lista.json()["unread"] == 0


def test_convite_para_quem_nao_tem_conta_nao_gera_notificacao(cena):
    """Sem conta não há a quem notificar dentro do app — só o e-mail."""
    resposta = client.post(
        f"/api/v1/workspaces/{cena['ws'].id}/invites",
        json={"email": "ninguem@n.com", "role": "member"},
        headers=_headers(cena["dono"]),
    )
    assert resposta.status_code == 200
    assert cena["db"].exec(select(Notification)).all() == []


def test_convite_expirado_nao_e_aceito(cena):
    _convidar(cena)
    convite = cena["db"].exec(select(WorkspaceInvite)).one()
    convite.expires_at = datetime.now(UTC) - timedelta(days=1)
    cena["db"].add(convite)
    cena["db"].commit()

    resposta = client.post(
        f"/api/v1/invites/accept/{convite.token}", headers=_headers(cena["convidado"])
    )
    assert resposta.status_code == 410
