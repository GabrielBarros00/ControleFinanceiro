"""Origem do pagamento por pagador (ADR 0004): método/conta por payer."""
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.models.payment_account import PaymentAccount
from app.models.transaction import Transaction, TransactionPayer
from app.models.workspace import WorkspaceMembership, WorkspaceRole

client = TestClient(app)


@pytest.fixture(name="ws_with_account")
def ws_with_account_fixture(db_session: Session, setup_data):
    db_session.add(WorkspaceMembership(
        workspace_id=setup_data["ws1"].id,
        user_id=setup_data["u2"].id,
        role=WorkspaceRole.member,
    ))
    account = PaymentAccount(workspace_id=setup_data["ws1"].id, name="Nubank", type="checking")
    foreign = PaymentAccount(workspace_id=setup_data["ws2"].id, name="Alheia", type="checking")
    inactive = PaymentAccount(
        workspace_id=setup_data["ws1"].id, name="Desativada", type="cash", active=False
    )
    db_session.add_all([account, foreign, inactive])
    db_session.commit()
    for obj in (account, foreign, inactive):
        db_session.refresh(obj)
    setup_data.update(account=account, foreign_account=foreign, inactive_account=inactive)
    return setup_data


def _payload(u1_id, u2_id=None, **overrides):
    payers = [{"user_id": u1_id, "amount": 90.0, "payment_method": "pix"}]
    splits = [{"user_id": u1_id, "split_method": "equal", "input_value": 0}]
    if u2_id:
        payers = [
            {"user_id": u1_id, "amount": 50.0, "payment_method": "pix"},
            {"user_id": u2_id, "amount": 40.0, "payment_method": "cash"},
        ]
        splits = [
            {"user_id": u1_id, "split_method": "equal", "input_value": 0},
            {"user_id": u2_id, "split_method": "equal", "input_value": 0},
        ]
    payload = {
        "title": "Mercado",
        "total_amount": 90.0,
        "transaction_date": "2026-06-10T12:00:00",
        "payers": payers,
        "splits": splits,
    }
    payload.update(overrides)
    return payload


def test_dois_pagadores_com_metodos_e_conta_diferentes(db_session, ws_with_account, override_get_session):
    ws1, u1, u2 = ws_with_account["ws1"], ws_with_account["u1"], ws_with_account["u2"]
    account = ws_with_account["account"]

    payload = _payload(u1.id, u2.id)
    payload["payers"][0]["account_id"] = account.id  # pix saiu da Nubank

    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        json=payload,
        headers=ws_with_account["headers1"],
    )
    assert resp.status_code == 200, resp.text
    payers = {p["user_id"]: p for p in resp.json()["payers"]}
    assert payers[u1.id]["payment_method"] == "pix"
    assert payers[u1.id]["account_id"] == account.id
    assert payers[u2.id]["payment_method"] == "cash"
    assert payers[u2.id]["account_id"] is None


def test_conta_de_outro_workspace_e_rejeitada_atomicamente(db_session, ws_with_account, override_get_session):
    ws1, u1 = ws_with_account["ws1"], ws_with_account["u1"]
    payload = _payload(u1.id)
    payload["payers"][0]["account_id"] = ws_with_account["foreign_account"].id

    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        json=payload,
        headers=ws_with_account["headers1"],
    )
    assert resp.status_code == 400
    assert "Conta inválida" in resp.json()["error"]["message"]
    db_session.expire_all()
    assert db_session.exec(
        select(Transaction).where(Transaction.workspace_id == ws1.id)
    ).all() == []


def test_conta_desativada_e_rejeitada(ws_with_account, override_get_session):
    ws1, u1 = ws_with_account["ws1"], ws_with_account["u1"]
    payload = _payload(u1.id)
    payload["payers"][0]["account_id"] = ws_with_account["inactive_account"].id

    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        json=payload,
        headers=ws_with_account["headers1"],
    )
    assert resp.status_code == 400
    assert "desativada" in resp.json()["error"]["message"]


def test_pagador_credit_card_exige_cartao_e_nao_usa_conta(ws_with_account, override_get_session):
    ws1, u1 = ws_with_account["ws1"], ws_with_account["u1"]

    # método credit_card no pagador sem cartão na transação → 422 (validator)
    payload = _payload(u1.id)
    payload["payers"][0]["payment_method"] = "credit_card"
    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        json=payload,
        headers=ws_with_account["headers1"],
    )
    assert resp.status_code == 422


def test_edicao_completa_troca_origem(db_session, ws_with_account, override_get_session):
    ws1, u1 = ws_with_account["ws1"], ws_with_account["u1"]
    account = ws_with_account["account"]
    headers = ws_with_account["headers1"]

    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        json=_payload(u1.id),
        headers=headers,
    )
    tx_id = resp.json()["id"]

    resp = client.put(
        f"/api/v1/workspaces/{ws1.id}/transactions/{tx_id}",
        json={
            "payers": [{
                "user_id": u1.id, "amount": 90.0,
                "payment_method": "debit_card", "account_id": account.id,
            }],
            "splits": [{"user_id": u1.id, "split_method": "equal", "input_value": 0}],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    payer = db_session.exec(
        select(TransactionPayer).where(TransactionPayer.transaction_id == tx_id)
    ).one()
    assert payer.payment_method == "debit_card"
    assert payer.account_id == account.id
