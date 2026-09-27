"""`GET /workspaces/` traz o `event_seq` de cada espaço (auditoria 2026-09-26, P2).

O cliente lê esse número no bootstrap, antes de a página buscar qualquer dado, e
o compara com o `seq` do `hello` do WebSocket: igual, nada mudou no meio e ele não
refaz todas as consultas. Por isso o número tem de ser EXATAMENTE o que o
WebSocket anuncia, e subir junto com toda mutação publicada.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.ws.routes import _current_seq


@pytest.fixture(name="client")
def client_fixture(override_get_session):
    return TestClient(app)


def _seq_da_lista(client, headers, ws_id) -> int:
    lista = client.get("/api/v1/workspaces/", headers=headers).json()
    return next(w["event_seq"] for w in lista if w["id"] == ws_id)


def _lanca(client, setup_data, titulo: str):
    ws, u1 = setup_data["ws1"], setup_data["u1"]
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/",
        json={
            "title": titulo, "total_amount": "50.00",
            "transaction_date": "2026-09-20T12:00:00Z",
            "payers": [{"user_id": u1.id, "amount": "50.00"}],
            "splits": [{"user_id": u1.id, "split_method": "equal", "input_value": "0"}],
        },
        headers=setup_data["headers1"],
    )
    assert res.status_code == 200, res.text


def test_event_seq_e_o_mesmo_do_websocket_e_sobe_com_a_mutacao(client, setup_data):
    ws, headers = setup_data["ws1"], setup_data["headers1"]

    antes = _seq_da_lista(client, headers, ws.id)
    assert antes == _current_seq(ws.id)

    _lanca(client, setup_data, "Mercado")

    depois = _seq_da_lista(client, headers, ws.id)
    assert depois > antes
    assert depois == _current_seq(ws.id)


def test_a_leitura_de_um_espaco_tambem_traz_o_seq(client, setup_data):
    ws, headers = setup_data["ws1"], setup_data["headers1"]
    _lanca(client, setup_data, "Padaria")
    _lanca(client, setup_data, "Feira")

    um = client.get(f"/api/v1/workspaces/{ws.id}", headers=headers).json()
    # Depois de duas mutações o seq não pode ser 0: um campo que ficasse no
    # default passaria neste teste só se o WebSocket também dissesse 0.
    assert um["event_seq"] >= 2
    assert um["event_seq"] == _current_seq(ws.id)
