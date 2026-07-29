import pytest
from datetime import datetime, timedelta, UTC
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.core.jwt import create_access_token
from app.models.user import User
from app.models.workspace import (
    Workspace,
    WorkspaceMembership,
    WorkspaceInvite,
    WorkspaceRole,
    InviteStatus,
)

client = TestClient(app)


def _headers(user: User) -> dict:
    return {"Cookie": f"access_token={create_access_token({'sub': str(user.id)})}"}


@pytest.fixture
def team(db_session: Session, override_get_session):
    """Workspace com um usuário por papel + um usuário de fora."""
    users = {}
    for key in ["owner", "admin", "member", "viewer", "outsider"]:
        u = User(name=key.title(), email=f"{key}@team.com", password_hash="hash")
        db_session.add(u)
        db_session.commit()
        db_session.refresh(u)
        users[key] = u

    ws = Workspace(name="Team WS", created_by_user_id=users["owner"].id)
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)

    for key in ["owner", "admin", "member", "viewer"]:
        db_session.add(WorkspaceMembership(
            workspace_id=ws.id, user_id=users[key].id, role=WorkspaceRole(key)
        ))
    db_session.commit()

    return {"ws": ws, "users": users, "db": db_session}


# --- Listagem de membros ---

def test_any_member_can_list_members(team):
    ws = team["ws"]
    res = client.get(f"/api/v1/workspaces/{ws.id}/members", headers=_headers(team["users"]["member"]))
    assert res.status_code == 200
    assert len(res.json()) == 4
    roles = {m["user_email"]: m["role"] for m in res.json()}
    assert roles["owner@team.com"] == "owner"


def test_viewer_ve_nome_mas_nao_email_dos_outros(team):
    """Viewer é o papel de MENOR privilégio e é quem alcança um workspace
    compartilhado com menos escrutínio — não precisa do endereço de todo mundo."""
    ws, users = team["ws"], team["users"]
    res = client.get(f"/api/v1/workspaces/{ws.id}/members", headers=_headers(users["viewer"]))
    assert res.status_code == 200

    por_nome = {m["user_name"]: m for m in res.json()}
    assert len(por_nome) == 4, "os nomes continuam todos visíveis"

    dono = next(m for m in res.json() if m["role"] == "owner")
    assert dono["user_email"] != "owner@team.com"
    assert "•" in dono["user_email"]
    assert dono["user_email"].endswith("@team.com"), "o domínio continua legível"

    # O próprio e-mail nunca é mascarado para o dono da conta
    eu = next(m for m in res.json() if m["user_id"] == users["viewer"].id)
    assert eu["user_email"] == users["viewer"].email


def test_member_ve_email_completo(team):
    ws = team["ws"]
    res = client.get(f"/api/v1/workspaces/{ws.id}/members", headers=_headers(team["users"]["member"]))
    emails = {m["user_email"] for m in res.json()}
    assert "owner@team.com" in emails


def test_outsider_cannot_list_members(team):
    ws = team["ws"]
    res = client.get(f"/api/v1/workspaces/{ws.id}/members", headers=_headers(team["users"]["outsider"]))
    assert res.status_code == 403


# --- Matriz papel × mutação básica ---

def test_viewer_cannot_mutate(team):
    ws = team["ws"]
    payload = {"title": "Aluguel", "base_amount": "1000", "day_of_month": 5}
    res = client.post(f"/api/v1/workspaces/{ws.id}/recurring", json=payload, headers=_headers(team["users"]["viewer"]))
    assert res.status_code == 403


def test_member_can_mutate(team):
    ws = team["ws"]
    payload = {"title": "Aluguel", "base_amount": "1000", "day_of_month": 5}
    res = client.post(f"/api/v1/workspaces/{ws.id}/recurring", json=payload, headers=_headers(team["users"]["member"]))
    assert res.status_code == 200


# --- Alteração de papel ---

def test_admin_can_demote_member_to_viewer(team):
    ws, users = team["ws"], team["users"]
    res = client.patch(
        f"/api/v1/workspaces/{ws.id}/members/{users['member'].id}",
        json={"role": "viewer"},
        headers=_headers(users["admin"]),
    )
    assert res.status_code == 200
    assert res.json()["role"] == "viewer"


def test_admin_cannot_promote_to_admin(team):
    ws, users = team["ws"], team["users"]
    res = client.patch(
        f"/api/v1/workspaces/{ws.id}/members/{users['member'].id}",
        json={"role": "admin"},
        headers=_headers(users["admin"]),
    )
    assert res.status_code == 403


def test_owner_can_promote_to_admin(team):
    ws, users = team["ws"], team["users"]
    res = client.patch(
        f"/api/v1/workspaces/{ws.id}/members/{users['member'].id}",
        json={"role": "admin"},
        headers=_headers(users["owner"]),
    )
    assert res.status_code == 200
    assert res.json()["role"] == "admin"


def test_nobody_can_promote_to_owner(team):
    ws, users = team["ws"], team["users"]
    res = client.patch(
        f"/api/v1/workspaces/{ws.id}/members/{users['member'].id}",
        json={"role": "owner"},
        headers=_headers(users["owner"]),
    )
    assert res.status_code == 400


def test_admin_cannot_change_owner_role(team):
    ws, users = team["ws"], team["users"]
    res = client.patch(
        f"/api/v1/workspaces/{ws.id}/members/{users['owner'].id}",
        json={"role": "member"},
        headers=_headers(users["admin"]),
    )
    assert res.status_code == 403


def test_cannot_change_own_role(team):
    ws, users = team["ws"], team["users"]
    res = client.patch(
        f"/api/v1/workspaces/{ws.id}/members/{users['admin'].id}",
        json={"role": "viewer"},
        headers=_headers(users["admin"]),
    )
    assert res.status_code == 400


def test_member_cannot_manage_roles(team):
    ws, users = team["ws"], team["users"]
    res = client.patch(
        f"/api/v1/workspaces/{ws.id}/members/{users['viewer'].id}",
        json={"role": "member"},
        headers=_headers(users["member"]),
    )
    assert res.status_code == 403


# --- Remoção e saída ---

def test_admin_can_remove_viewer(team):
    ws, users, db = team["ws"], team["users"], team["db"]
    res = client.delete(
        f"/api/v1/workspaces/{ws.id}/members/{users['viewer'].id}",
        headers=_headers(users["admin"]),
    )
    assert res.status_code == 200
    gone = db.exec(select(WorkspaceMembership).where(
        WorkspaceMembership.workspace_id == ws.id,
        WorkspaceMembership.user_id == users["viewer"].id,
    )).first()
    assert gone is None


def test_admin_cannot_remove_owner(team):
    ws, users = team["ws"], team["users"]
    res = client.delete(
        f"/api/v1/workspaces/{ws.id}/members/{users['owner'].id}",
        headers=_headers(users["admin"]),
    )
    assert res.status_code == 403


def test_member_leaves_workspace(team):
    ws, users, db = team["ws"], team["users"], team["db"]
    res = client.post(f"/api/v1/workspaces/{ws.id}/leave", headers=_headers(users["member"]))
    assert res.status_code == 200
    gone = db.exec(select(WorkspaceMembership).where(
        WorkspaceMembership.workspace_id == ws.id,
        WorkspaceMembership.user_id == users["member"].id,
    )).first()
    assert gone is None


def test_owner_cannot_leave(team):
    ws, users = team["ws"], team["users"]
    res = client.post(f"/api/v1/workspaces/{ws.id}/leave", headers=_headers(users["owner"]))
    assert res.status_code == 400


# --- Convites por email ---

def test_member_cannot_invite(team):
    ws, users = team["ws"], team["users"]
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/invites",
        json={"email": "x@y.com", "role": "member"},
        headers=_headers(users["member"]),
    )
    assert res.status_code == 403


def test_invite_existing_user_aguarda_aceite(team):
    """Usuário JÁ cadastrado não entra sem consentimento.

    Antes, convidar por e-mail colocava a pessoa no workspace na hora: quem
    soubesse um e-mail dava a si mesmo uma plateia para as finanças alheias, e o
    convidado passava a ver as contas de outra família sem saber. Agora nasce um
    convite pendente + uma notificação dentro do app.
    """
    ws, users, db = team["ws"], team["users"], team["db"]
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/invites",
        json={"email": "outsider@team.com", "role": "member"},
        headers=_headers(users["admin"]),
    )
    assert res.status_code == 200
    assert res.json()["status"] == "invite_sent"

    m = db.exec(select(WorkspaceMembership).where(
        WorkspaceMembership.workspace_id == ws.id,
        WorkspaceMembership.user_id == users["outsider"].id,
    )).first()
    assert m is None, "ninguém entra no workspace sem aceitar"

    from app.models.notification import Notification
    avisos = db.exec(
        select(Notification).where(Notification.user_id == users["outsider"].id)
    ).all()
    assert len(avisos) == 1
    assert avisos[0].type.value == "workspace_invite"
    assert avisos[0].invite_token is not None
    assert avisos[0].read_at is None

    # Convidar de novo → já é membro
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/invites",
        json={"email": "outsider@team.com", "role": "member"},
        headers=_headers(users["admin"]),
    )
    assert res.status_code == 400


def test_admin_cannot_invite_admin(team):
    ws, users = team["ws"], team["users"]
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/invites",
        json={"email": "novo@x.com", "role": "admin"},
        headers=_headers(users["admin"]),
    )
    assert res.status_code == 403


def test_invite_unknown_email_creates_pending_and_register_accepts(team):
    ws, users, db = team["ws"], team["users"], team["db"]
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/invites",
        json={"email": "novata@example.com", "role": "viewer"},
        headers=_headers(users["admin"]),
    )
    assert res.status_code == 200
    assert res.json()["status"] == "invite_sent"

    # Convite duplicado pendente → 400
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/invites",
        json={"email": "novata@example.com", "role": "viewer"},
        headers=_headers(users["admin"]),
    )
    assert res.status_code == 400

    # Registro pelo LINK do convite (token no corpo) = consentimento explícito
    token = db.exec(select(WorkspaceInvite).where(
        WorkspaceInvite.email == "novata@example.com"
    )).first().token
    res = client.post("/api/v1/auth/register", json={
        "name": "Novata", "email": "novata@example.com", "password": "secret123",
        "invite_token": token,
    })
    assert res.status_code == 200
    new_user = db.exec(select(User).where(User.email == "novata@example.com")).first()

    m = db.exec(select(WorkspaceMembership).where(
        WorkspaceMembership.workspace_id == ws.id,
        WorkspaceMembership.user_id == new_user.id,
    )).first()
    assert m is not None
    assert m.role == WorkspaceRole.viewer

    invite = db.exec(select(WorkspaceInvite).where(
        WorkspaceInvite.email == "novata@example.com"
    )).first()
    assert invite.status == InviteStatus.accepted


def test_registro_sem_o_token_do_convite_nao_entra_no_workspace(team):
    """Cadastrar-se por conta própria NÃO pode dar acesso ao workspace alheio.

    Antes, `register` aceitava TODO convite pendente para aquele e-mail: quem
    soubesse o endereço de alguém dava a si mesmo uma plateia para as próprias
    finanças — e colocava a pessoa dentro das finanças de outra família — sem
    ela aceitar nada. A E15 corrigiu isso para quem JÁ tinha conta; o caminho de
    registro tinha ficado para trás. O convite agora vira NOTIFICAÇÃO.
    """
    from app.models.notification import Notification

    ws, users, db = team["ws"], team["users"], team["db"]
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/invites",
        json={"email": "alheia@example.com", "role": "member"},
        headers=_headers(users["admin"]),
    )
    assert res.status_code == 200

    # Cadastro POR FORA do link: nenhum token acompanha
    res = client.post("/api/v1/auth/register", json={
        "name": "Alheia", "email": "alheia@example.com", "password": "secret123",
    })
    assert res.status_code == 200
    nova = db.exec(select(User).where(User.email == "alheia@example.com")).first()

    m = db.exec(select(WorkspaceMembership).where(
        WorkspaceMembership.workspace_id == ws.id,
        WorkspaceMembership.user_id == nova.id,
    )).first()
    assert m is None, "entrou no workspace de terceiros sem consentir"

    invite = db.exec(select(WorkspaceInvite).where(
        WorkspaceInvite.email == "alheia@example.com"
    )).first()
    assert invite.status == InviteStatus.pending, "o convite foi consumido sem aceite"

    # Mas o convite não some: chega como aviso, com as duas saídas
    aviso = db.exec(select(Notification).where(Notification.user_id == nova.id)).first()
    assert aviso is not None, "o convite sumiu — sem membership e sem notificação"
    assert aviso.invite_token == invite.token
    assert aviso.workspace_id == ws.id

    # E o aceite explícito continua funcionando pelo endpoint de convite
    res = client.post(f"/api/v1/invites/accept/{invite.token}", headers=_headers(nova))
    assert res.status_code == 200, res.text
    m = db.exec(select(WorkspaceMembership).where(
        WorkspaceMembership.workspace_id == ws.id,
        WorkspaceMembership.user_id == nova.id,
    )).first()
    assert m is not None


# --- Convites por link ---

def test_invite_link_flow(team):
    ws, users, db = team["ws"], team["users"], team["db"]
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/invites/link",
        json={"role": "member", "expires_days": 7},
        headers=_headers(users["owner"]),
    )
    assert res.status_code == 200
    token = res.json()["token"]
    assert token in res.json()["url"]

    # Info do convite para o usuário de fora
    res = client.get(f"/api/v1/invites/info/{token}", headers=_headers(users["outsider"]))
    assert res.status_code == 200
    assert res.json()["valid"] is True
    assert res.json()["workspace_name"] == "Team WS"

    # Aceite
    res = client.post(f"/api/v1/invites/accept/{token}", headers=_headers(users["outsider"]))
    assert res.status_code == 200
    m = db.exec(select(WorkspaceMembership).where(
        WorkspaceMembership.workspace_id == ws.id,
        WorkspaceMembership.user_id == users["outsider"].id,
    )).first()
    assert m is not None

    # Aceitar de novo → já é membro
    res = client.post(f"/api/v1/invites/accept/{token}", headers=_headers(users["outsider"]))
    assert res.status_code == 400


def test_invite_link_max_uses(team):
    ws, users, db = team["ws"], team["users"], team["db"]
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/invites/link",
        json={"role": "viewer", "expires_days": 7, "max_uses": 1},
        headers=_headers(users["owner"]),
    )
    token = res.json()["token"]

    res = client.post(f"/api/v1/invites/accept/{token}", headers=_headers(users["outsider"]))
    assert res.status_code == 200

    extra = User(name="Extra", email="extra@team.com", password_hash="hash")
    db.add(extra)
    db.commit()
    db.refresh(extra)
    res = client.post(f"/api/v1/invites/accept/{token}", headers=_headers(extra))
    assert res.status_code in (404, 410)  # esgotado


def test_revoked_invite_cannot_be_accepted(team):
    ws, users = team["ws"], team["users"]
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/invites/link",
        json={"role": "member", "expires_days": 7},
        headers=_headers(users["owner"]),
    )
    invite_id = res.json()["id"]
    token = res.json()["token"]

    res = client.delete(
        f"/api/v1/workspaces/{ws.id}/invites/{invite_id}",
        headers=_headers(users["admin"]),
    )
    assert res.status_code == 200

    res = client.post(f"/api/v1/invites/accept/{token}", headers=_headers(users["outsider"]))
    assert res.status_code == 404


def test_revogar_convite_encerra_a_notificacao(team):
    """Revogar tem que apagar o aviso do app junto.

    O convite pendente vira um MODAL na cara do convidado (é a primeira coisa
    depois do onboarding). Revogado sem resolver a notificação, o modal
    continuava aparecendo com um "Aceitar" que só devolve 404 — e o contador de
    não lidas não tinha mais nenhuma ação capaz de zerá-lo.
    """
    from app.models.notification import Notification

    ws, users, db = team["ws"], team["users"], team["db"]
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/invites",
        json={"email": "outsider@team.com", "role": "member"},
        headers=_headers(users["admin"]),
    )
    assert res.status_code == 200
    invite_id = res.json()["invite"]["id"]

    aviso = db.exec(
        select(Notification).where(Notification.user_id == users["outsider"].id)
    ).first()
    assert aviso is not None and aviso.read_at is None

    res = client.delete(
        f"/api/v1/workspaces/{ws.id}/invites/{invite_id}",
        headers=_headers(users["admin"]),
    )
    assert res.status_code == 200

    db.refresh(aviso)
    assert aviso.read_at is not None, "o convite morreu mas o aviso continuou pendente"

    # E o convidado não vê mais nada pendente para responder
    res = client.get("/api/v1/notifications", headers=_headers(users["outsider"]))
    assert res.status_code == 200
    assert res.json()["unread"] == 0


def test_expired_invite_cannot_be_accepted(team):
    ws, users, db = team["ws"], team["users"], team["db"]
    invite = WorkspaceInvite(
        workspace_id=ws.id,
        email=None,
        role=WorkspaceRole.member,
        invited_by_user_id=users["owner"].id,
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)

    res = client.post(f"/api/v1/invites/accept/{invite.token}", headers=_headers(users["outsider"]))
    assert res.status_code == 410


def test_email_invite_bound_to_email(team):
    ws, users, db = team["ws"], team["users"], team["db"]
    invite = WorkspaceInvite(
        workspace_id=ws.id,
        email="alguem@especifico.com",
        role=WorkspaceRole.member,
        invited_by_user_id=users["owner"].id,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)

    # Outro usuário não pode aceitar convite direcionado
    res = client.post(f"/api/v1/invites/accept/{invite.token}", headers=_headers(users["outsider"]))
    assert res.status_code == 403


def test_admin_lists_invites(team):
    ws, users = team["ws"], team["users"]
    client.post(
        f"/api/v1/workspaces/{ws.id}/invites",
        json={"email": "pendente@example.com", "role": "member"},
        headers=_headers(users["admin"]),
    )
    res = client.get(f"/api/v1/workspaces/{ws.id}/invites", headers=_headers(users["admin"]))
    assert res.status_code == 200
    assert len(res.json()) >= 1

    # Member não pode listar convites
    res = client.get(f"/api/v1/workspaces/{ws.id}/invites", headers=_headers(users["member"]))
    assert res.status_code == 403
