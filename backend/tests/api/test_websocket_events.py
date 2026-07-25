import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.core.jwt import create_access_token
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.models.sync_event import SyncEvent


def _headers(user: User) -> dict:
    return {"Cookie": f"access_token={create_access_token({'sub': str(user.id)})}"}


@pytest.fixture
def rt(db_session: Session, override_get_session):
    """Workspace com dois membros + um usuário de fora."""
    users = {}
    for key in ["owner", "member", "outsider"]:
        u = User(name=key, email=f"{key}@rt.com", password_hash="hash")
        db_session.add(u)
        db_session.commit()
        db_session.refresh(u)
        users[key] = u

    ws = Workspace(name="RT WS", created_by_user_id=users["owner"].id)
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)

    db_session.add(WorkspaceMembership(workspace_id=ws.id, user_id=users["owner"].id, role="owner"))
    db_session.add(WorkspaceMembership(workspace_id=ws.id, user_id=users["member"].id, role="member"))
    db_session.commit()

    return {"ws": ws, "users": users, "db": db_session}


def test_ws_requires_auth(rt):
    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/ws/workspaces/{rt['ws'].id}") as sock:
            with pytest.raises(WebSocketDisconnect) as exc:
                sock.receive_json()
            assert exc.value.code == 4401


def test_ws_rejects_non_member(rt):
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/api/v1/ws/workspaces/{rt['ws'].id}",
            headers=_headers(rt["users"]["outsider"]),
        ) as sock:
            with pytest.raises(WebSocketDisconnect) as exc:
                sock.receive_json()
            assert exc.value.code == 4403


def test_two_clients_receive_seq_consistent_events(rt):
    ws, users, db = rt["ws"], rt["users"], rt["db"]
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/api/v1/ws/workspaces/{ws.id}", headers=_headers(users["owner"])
        ) as sock1, client.websocket_connect(
            f"/api/v1/ws/workspaces/{ws.id}", headers=_headers(users["member"])
        ) as sock2:
            hello1 = sock1.receive_json()
            hello2 = sock2.receive_json()
            assert hello1["type"] == "hello"
            assert hello1["seq"] == 0
            assert hello2["seq"] == 0

            # Mutação REST → ambos os clientes recebem o evento
            res = client.post(
                f"/api/v1/workspaces/{ws.id}/recurring",
                json={"title": "Internet", "base_amount": "99.90", "day_of_month": 10},
                headers=_headers(users["member"]),
            )
            assert res.status_code == 200

            evt1 = sock1.receive_json()
            evt2 = sock2.receive_json()
            assert evt1["type"] == "recurring.created"
            assert evt1["seq"] == 1
            assert evt2["seq"] == 1
            assert evt1["workspace_id"] == ws.id
            assert evt1["actor_user_id"] == users["member"].id

            # Segunda mutação → seq incrementa
            res = client.post(
                f"/api/v1/workspaces/{ws.id}/recurring",
                json={"title": "Luz", "base_amount": "150", "day_of_month": 15},
                headers=_headers(users["member"]),
            )
            assert res.status_code == 200
            assert sock1.receive_json()["seq"] == 2
            assert sock2.receive_json()["seq"] == 2

    # Eventos persistidos com unicidade (workspace_id, seq)
    events = db.exec(select(SyncEvent).where(SyncEvent.workspace_id == ws.id)).all()
    assert [e.seq for e in sorted(events, key=lambda e: e.seq)] == [1, 2]


def test_bulk_import_emits_single_event(rt):
    ws, users = rt["ws"], rt["users"]
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/api/v1/ws/workspaces/{ws.id}", headers=_headers(users["owner"])
        ) as sock:
            sock.receive_json()  # hello

            res = client.post(
                f"/api/v1/workspaces/{ws.id}/transactions/bulk",
                json=[
                    {"title": "A", "total_amount": "10.00", "transaction_date": "2026-07-01T00:00:00Z"},
                    {"title": "B", "total_amount": "20.00", "transaction_date": "2026-07-02T00:00:00Z"},
                    {"title": "C", "total_amount": "30.00", "transaction_date": "2026-07-03T00:00:00Z"},
                ],
                headers=_headers(users["member"]),
            )
            assert res.status_code == 200
            assert res.json()["created"] == 3

            evt = sock.receive_json()
            assert evt["type"] == "transaction.bulk_created"
            assert evt["seq"] == 1

            # Nada mais na fila: uma nova mutação chega com seq 2 (sem eventos intermediários)
            client.post(
                f"/api/v1/workspaces/{ws.id}/recurring",
                json={"title": "X", "base_amount": "1", "day_of_month": 1},
                headers=_headers(users["member"]),
            )
            evt = sock.receive_json()
            assert evt["type"] == "recurring.created"
            assert evt["seq"] == 2


def test_events_isolated_per_workspace(rt, db_session):
    ws, users = rt["ws"], rt["users"]
    # Outro workspace do mesmo dono
    other = Workspace(name="Outro WS", created_by_user_id=users["owner"].id)
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)
    db_session.add(WorkspaceMembership(workspace_id=other.id, user_id=users["owner"].id, role="owner"))
    db_session.commit()

    with TestClient(app) as client:
        with client.websocket_connect(
            f"/api/v1/ws/workspaces/{ws.id}", headers=_headers(users["owner"])
        ) as sock:
            sock.receive_json()  # hello

            # Mutação no OUTRO workspace não chega neste socket
            client.post(
                f"/api/v1/workspaces/{other.id}/recurring",
                json={"title": "Fora", "base_amount": "5", "day_of_month": 2},
                headers=_headers(users["owner"]),
            )
            # Mutação no workspace certo chega em seguida
            client.post(
                f"/api/v1/workspaces/{ws.id}/recurring",
                json={"title": "Dentro", "base_amount": "5", "day_of_month": 3},
                headers=_headers(users["owner"]),
            )
            evt = sock.receive_json()
            assert evt["workspace_id"] == ws.id
            assert evt["type"] == "recurring.created"


def test_removed_member_socket_is_closed(rt):
    """Membro removido recebe o evento e tem a conexão WS revogada (4403)."""
    ws, users = rt["ws"], rt["users"]
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/api/v1/ws/workspaces/{ws.id}", headers=_headers(users["member"])
        ) as sock:
            sock.receive_json()  # hello

            res = client.delete(
                f"/api/v1/workspaces/{ws.id}/members/{users['member'].id}",
                headers=_headers(users["owner"]),
            )
            assert res.status_code == 200

            evt = sock.receive_json()
            assert evt["type"] == "member.removed"

            with pytest.raises(WebSocketDisconnect) as exc:
                sock.receive_json()
            assert exc.value.code == 4403


def test_client_ping_gets_pong(rt):
    ws, users = rt["ws"], rt["users"]
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/api/v1/ws/workspaces/{ws.id}", headers=_headers(users["owner"])
        ) as sock:
            sock.receive_json()  # hello
            sock.send_text("ping")
            assert sock.receive_json()["type"] == "pong"


# --- Cobertura de tempo real das mutações que antes ficavam mudas -----------


def test_autor_da_acao_tambem_recebe_o_evento(rt):
    """Quem faz a mutação recebe o mesmo envelope que os demais membros.

    O broadcast vai para TODOS os sockets da sala, inclusive o do autor — é o
    que permite a outra aba do mesmo usuário atualizar sozinha.
    """
    ws, users = rt["ws"], rt["users"]
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/api/v1/ws/workspaces/{ws.id}", headers=_headers(users["member"])
        ) as sock_autor, client.websocket_connect(
            f"/api/v1/ws/workspaces/{ws.id}", headers=_headers(users["owner"])
        ) as sock_outro:
            sock_autor.receive_json()
            sock_outro.receive_json()

            res = client.post(
                f"/api/v1/workspaces/{ws.id}/categories",
                json={"name": "Lazer"},
                headers=_headers(users["member"]),
            )
            assert res.status_code in (200, 201)

            evt_autor = sock_autor.receive_json()
            evt_outro = sock_outro.receive_json()
            assert evt_autor["type"] == "category.created"
            assert evt_autor["actor_user_id"] == users["member"].id
            # Mesmo envelope, mesmo seq: nenhum tratamento especial para o autor
            assert evt_autor == evt_outro


def test_convite_por_email_emite_evento(rt):
    ws, users = rt["ws"], rt["users"]
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/api/v1/ws/workspaces/{ws.id}", headers=_headers(users["owner"])
        ) as sock:
            sock.receive_json()
            res = client.post(
                f"/api/v1/workspaces/{ws.id}/invites",
                json={"email": "novo@convidado.com", "role": "member"},
                headers=_headers(users["owner"]),
            )
            assert res.status_code == 200
            assert sock.receive_json()["type"] == "invite.created"


def test_link_de_convite_e_revogacao_emitem_evento(rt):
    ws, users = rt["ws"], rt["users"]
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/api/v1/ws/workspaces/{ws.id}", headers=_headers(users["owner"])
        ) as sock:
            sock.receive_json()

            res = client.post(
                f"/api/v1/workspaces/{ws.id}/invites/link",
                json={"role": "member", "expires_days": 7},
                headers=_headers(users["owner"]),
            )
            assert res.status_code == 200
            assert sock.receive_json()["type"] == "invite.created"
            invite_id = res.json()["id"]

            res = client.delete(
                f"/api/v1/workspaces/{ws.id}/invites/{invite_id}",
                headers=_headers(users["owner"]),
            )
            assert res.status_code == 200
            assert sock.receive_json()["type"] == "invite.revoked"


def test_renomear_perfil_avisa_os_workspaces_do_usuario(rt):
    """O nome aparece no extrato e nas dívidas — a troca precisa chegar aos outros."""
    ws, users = rt["ws"], rt["users"]
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/api/v1/ws/workspaces/{ws.id}", headers=_headers(users["owner"])
        ) as sock:
            sock.receive_json()

            res = client.patch(
                "/api/v1/auth/me",
                json={"name": "Nome Novo"},
                headers=_headers(users["member"]),
            )
            assert res.status_code == 200

            evt = sock.receive_json()
            assert evt["type"] == "member.updated"
            assert evt["resource"]["id"] == users["member"].id


def test_troca_de_moeda_base_emite_evento_de_resync(rt):
    ws, users = rt["ws"], rt["users"]
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/api/v1/ws/workspaces/{ws.id}", headers=_headers(users["member"])
        ) as sock:
            sock.receive_json()

            res = client.put(
                f"/api/v1/workspaces/{ws.id}",
                json={"base_currency": "usd"},
                headers=_headers(users["owner"]),
            )
            assert res.status_code == 200
            assert res.json()["base_currency"] == "USD"  # normalizado para maiúsculas

            assert sock.receive_json()["type"] == "workspace.updated"
            assert sock.receive_json()["type"] == "workspace.currency_changed"
