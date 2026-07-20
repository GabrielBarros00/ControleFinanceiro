"""Settle up: registrar acertos desconta do saldo de dívidas."""
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import app
from app.models.workspace import WorkspaceMembership, WorkspaceRole

client = TestClient(app)


@pytest.fixture(name="two_member_ws")
def two_member_ws_fixture(db_session: Session, setup_data):
    db_session.add(WorkspaceMembership(
        workspace_id=setup_data["ws1"].id,
        user_id=setup_data["u2"].id,
        role=WorkspaceRole.member,
    ))
    db_session.commit()
    return setup_data


def _create_shared_expense(ws_id, u1_id, u2_id, headers, total=90.0):
    payload = {
        "title": "Mercado",
        "total_amount": total,
        "transaction_date": "2026-07-18T12:00:00",
        "payers": [{"user_id": u1_id, "amount": total}],
        "splits": [
            {"user_id": u1_id, "split_method": "equal", "input_value": 0},
            {"user_id": u2_id, "split_method": "equal", "input_value": 0},
        ],
    }
    resp = client.post(f"/api/v1/workspaces/{ws_id}/transactions/", json=payload, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _debts(ws_id, headers):
    resp = client.get(f"/api/v1/workspaces/{ws_id}/debts", headers=headers)
    assert resp.status_code == 200
    return resp.json()


def test_settlement_reduces_and_clears_debt(two_member_ws, override_get_session):
    ws1, u1, u2 = two_member_ws["ws1"], two_member_ws["u1"], two_member_ws["u2"]
    headers = two_member_ws["headers1"]

    _create_shared_expense(ws1.id, u1.id, u2.id, headers, total=90.0)

    debts = _debts(ws1.id, headers)
    assert debts == [{"debtor_id": u2.id, "creditor_id": u1.id, "amount": "45.00"}]

    # Acerto parcial de 20
    resp = client.post(f"/api/v1/workspaces/{ws1.id}/settlements", json={
        "from_user_id": u2.id, "to_user_id": u1.id, "amount": 20.0, "note": "pix"
    }, headers=headers)
    assert resp.status_code == 200, resp.text

    debts = _debts(ws1.id, headers)
    assert debts == [{"debtor_id": u2.id, "creditor_id": u1.id, "amount": "25.00"}]

    # Quita o restante
    resp = client.post(f"/api/v1/workspaces/{ws1.id}/settlements", json={
        "from_user_id": u2.id, "to_user_id": u1.id, "amount": 25.0
    }, headers=headers)
    assert resp.status_code == 200

    assert _debts(ws1.id, headers) == []


def test_delete_settlement_restores_debt(two_member_ws, override_get_session):
    ws1, u1, u2 = two_member_ws["ws1"], two_member_ws["u1"], two_member_ws["u2"]
    headers = two_member_ws["headers1"]

    _create_shared_expense(ws1.id, u1.id, u2.id, headers, total=60.0)
    resp = client.post(f"/api/v1/workspaces/{ws1.id}/settlements", json={
        "from_user_id": u2.id, "to_user_id": u1.id, "amount": 30.0
    }, headers=headers)
    settlement_id = resp.json()["id"]
    assert _debts(ws1.id, headers) == []

    resp = client.delete(f"/api/v1/workspaces/{ws1.id}/settlements/{settlement_id}", headers=headers)
    assert resp.status_code == 200

    debts = _debts(ws1.id, headers)
    assert debts == [{"debtor_id": u2.id, "creditor_id": u1.id, "amount": "30.00"}]


def test_settlement_history_listed_desc(two_member_ws, override_get_session):
    ws1, u1, u2 = two_member_ws["ws1"], two_member_ws["u1"], two_member_ws["u2"]
    headers = two_member_ws["headers1"]

    # Dívida u2→u1 (u1 pagou 90, meio a meio) e acerto parcial
    _create_shared_expense(ws1.id, u1.id, u2.id, headers, total=90.0)
    resp = client.post(f"/api/v1/workspaces/{ws1.id}/settlements", json={
        "from_user_id": u2.id, "to_user_id": u1.id, "amount": 10.0,
        "settled_at": "2026-07-01T10:00:00",
    }, headers=headers)
    assert resp.status_code == 200, resp.text

    # Segunda despesa inverte a dívida líquida (u2 paga 100): u1 passa a dever 15
    payload = {
        "title": "Farmácia",
        "total_amount": 100.0,
        "transaction_date": "2026-07-05T12:00:00",
        "payers": [{"user_id": u2.id, "amount": 100.0}],
        "splits": [
            {"user_id": u1.id, "split_method": "equal", "input_value": 0},
            {"user_id": u2.id, "split_method": "equal", "input_value": 0},
        ],
    }
    resp = client.post(f"/api/v1/workspaces/{ws1.id}/transactions/", json=payload, headers=headers)
    assert resp.status_code == 200, resp.text

    resp = client.post(f"/api/v1/workspaces/{ws1.id}/settlements", json={
        "from_user_id": u1.id, "to_user_id": u2.id, "amount": 5.0,
        "settled_at": "2026-07-10T10:00:00",
    }, headers=headers)
    assert resp.status_code == 200, resp.text

    resp = client.get(f"/api/v1/workspaces/{ws1.id}/settlements", headers=headers)
    assert resp.status_code == 200
    history = resp.json()
    assert len(history) == 2
    assert history[0]["settled_at"] > history[1]["settled_at"]


def test_settlement_validations(two_member_ws, override_get_session):
    ws1, u1, u2 = two_member_ws["ws1"], two_member_ws["u1"], two_member_ws["u2"]
    headers = two_member_ws["headers1"]

    # Pagador == recebedor
    resp = client.post(f"/api/v1/workspaces/{ws1.id}/settlements", json={
        "from_user_id": u1.id, "to_user_id": u1.id, "amount": 10.0
    }, headers=headers)
    assert resp.status_code == 400

    # Não-membro
    resp = client.post(f"/api/v1/workspaces/{ws1.id}/settlements", json={
        "from_user_id": u1.id, "to_user_id": 99999, "amount": 10.0
    }, headers=headers)
    assert resp.status_code == 400

    # Valor não-positivo
    resp = client.post(f"/api/v1/workspaces/{ws1.id}/settlements", json={
        "from_user_id": u2.id, "to_user_id": u1.id, "amount": 0
    }, headers=headers)
    assert resp.status_code == 422

    # Workspace alheio (u1 não é membro de ws2)
    ws2 = two_member_ws["ws2"]
    resp = client.post(f"/api/v1/workspaces/{ws2.id}/settlements", json={
        "from_user_id": u1.id, "to_user_id": u2.id, "amount": 10.0
    }, headers=headers)
    assert resp.status_code in (403, 404)


def test_settlement_sem_divida_e_rejeitado(two_member_ws, override_get_session):
    """ADR 0009: acerto sem dívida na direção informada é 400."""
    ws1, u1, u2 = two_member_ws["ws1"], two_member_ws["u1"], two_member_ws["u2"]
    headers = two_member_ws["headers1"]

    resp = client.post(f"/api/v1/workspaces/{ws1.id}/settlements", json={
        "from_user_id": u2.id, "to_user_id": u1.id, "amount": 10.0
    }, headers=headers)
    assert resp.status_code == 400
    assert "Não há dívida" in resp.json()["error"]["message"]


def test_settlement_direcao_invertida_e_rejeitado(two_member_ws, override_get_session):
    ws1, u1, u2 = two_member_ws["ws1"], two_member_ws["u1"], two_member_ws["u2"]
    headers = two_member_ws["headers1"]

    # Dívida real: u2 deve 45 a u1 — acertar u1→u2 é direção errada
    _create_shared_expense(ws1.id, u1.id, u2.id, headers, total=90.0)
    resp = client.post(f"/api/v1/workspaces/{ws1.id}/settlements", json={
        "from_user_id": u1.id, "to_user_id": u2.id, "amount": 10.0
    }, headers=headers)
    assert resp.status_code == 400


def test_settlement_sobrepagamento_e_rejeitado(two_member_ws, override_get_session):
    """ADR 0009: valor acima do saldo criaria crédito artificial — 400."""
    ws1, u1, u2 = two_member_ws["ws1"], two_member_ws["u1"], two_member_ws["u2"]
    headers = two_member_ws["headers1"]

    _create_shared_expense(ws1.id, u1.id, u2.id, headers, total=90.0)  # u2 deve 45
    resp = client.post(f"/api/v1/workspaces/{ws1.id}/settlements", json={
        "from_user_id": u2.id, "to_user_id": u1.id, "amount": 45.01
    }, headers=headers)
    assert resp.status_code == 400
    assert "excede" in resp.json()["error"]["message"]

    # No limite exato passa
    resp = client.post(f"/api/v1/workspaces/{ws1.id}/settlements", json={
        "from_user_id": u2.id, "to_user_id": u1.id, "amount": 45.00
    }, headers=headers)
    assert resp.status_code == 200, resp.text


def test_member_nao_registra_acerto_de_terceiro(two_member_ws, override_get_session):
    """ADR 0009: member só registra acertos em que ELE é o pagador."""
    ws1, u1, u2 = two_member_ws["ws1"], two_member_ws["u1"], two_member_ws["u2"]

    # Dívida real u2→u1; u2 (member) tenta registrar acerto pago por u1
    _create_shared_expense(ws1.id, u1.id, u2.id, two_member_ws["headers1"], total=90.0)
    resp = client.post(f"/api/v1/workspaces/{ws1.id}/settlements", json={
        "from_user_id": u1.id, "to_user_id": u2.id, "amount": 10.0
    }, headers=two_member_ws["headers2"])
    assert resp.status_code == 403

    # Na direção em que u2 é o pagador, member pode
    resp = client.post(f"/api/v1/workspaces/{ws1.id}/settlements", json={
        "from_user_id": u2.id, "to_user_id": u1.id, "amount": 10.0
    }, headers=two_member_ws["headers2"])
    assert resp.status_code == 200, resp.text
