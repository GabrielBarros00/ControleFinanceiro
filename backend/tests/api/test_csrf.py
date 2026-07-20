"""CSRF por validação de Origin/Referer (SEC-002).

Navegadores sempre enviam Origin em mutações cross-origin — origem fora da
lista é bloqueada. Sem Origin/Referer (curl, testes) passa: não é vetor CSRF.
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _payload(setup_data):
    u1 = setup_data["u1"]
    return {
        "title": "Compra",
        "total_amount": 10.0,
        "transaction_date": "2026-05-10T10:00:00",
        "payers": [{"user_id": u1.id, "amount": 10.0}],
        "splits": [{"user_id": u1.id, "split_method": "equal", "input_value": 0}],
    }


def test_origem_desconhecida_e_bloqueada(setup_data, override_get_session):
    ws1 = setup_data["ws1"]
    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        json=_payload(setup_data),
        headers={**setup_data["headers1"], "Origin": "https://malicioso.example"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["message"] == "Origem da requisição não permitida"


def test_referer_desconhecido_e_bloqueado(setup_data, override_get_session):
    ws1 = setup_data["ws1"]
    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        json=_payload(setup_data),
        headers={**setup_data["headers1"], "Referer": "https://malicioso.example/form"},
    )
    assert resp.status_code == 403


def test_origem_permitida_passa(setup_data, override_get_session):
    ws1 = setup_data["ws1"]
    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        json=_payload(setup_data),
        headers={**setup_data["headers1"], "Origin": "http://localhost:5173"},
    )
    assert resp.status_code == 200, resp.text


def test_sem_origin_nem_referer_passa(setup_data, override_get_session):
    """Clientes não-browser não enviam Origin — não são vetor de CSRF."""
    ws1 = setup_data["ws1"]
    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        json=_payload(setup_data),
        headers=setup_data["headers1"],
    )
    assert resp.status_code == 200, resp.text


def test_get_nao_e_afetado(setup_data, override_get_session):
    ws1 = setup_data["ws1"]
    resp = client.get(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        headers={**setup_data["headers1"], "Origin": "https://malicioso.example"},
    )
    assert resp.status_code == 200
