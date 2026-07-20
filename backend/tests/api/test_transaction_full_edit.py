"""Divisão por item, método de pagamento, edição completa e trava de paga."""
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.models.transaction import (
    TransactionPayer,
    TransactionSplit,
)
from app.models.workspace import WorkspaceMembership, WorkspaceRole

client = TestClient(app)


@pytest.fixture(name="two_member_ws")
def two_member_ws_fixture(db_session: Session, setup_data):
    """ws1 com u1 (owner) e u2 (member)."""
    db_session.add(WorkspaceMembership(
        workspace_id=setup_data["ws1"].id,
        user_id=setup_data["u2"].id,
        role=WorkspaceRole.member,
    ))
    db_session.commit()
    return setup_data


def _base_payload(u1_id, total=90.0, **overrides):
    payload = {
        "title": "Mercado",
        "total_amount": total,
        "transaction_date": "2026-07-18T12:00:00",
        "payers": [{"user_id": u1_id, "amount": total}],
        "splits": [{"user_id": u1_id, "split_method": "equal", "input_value": 0}],
    }
    payload.update(overrides)
    return payload


def _item_mode_payload(u1_id, u2_id):
    """Carne 60 dividida igual (u1+u2); Cerveja 3×10 só do u2. Total 90."""
    return {
        "title": "Churrasco",
        "total_amount": 90.0,
        "transaction_date": "2026-07-18T12:00:00",
        "split_mode": "item",
        "payers": [{"user_id": u1_id, "amount": 90.0}],
        "splits": [],
        "items": [
            {
                "title": "Carne", "amount": 60.0, "position": 0,
                "shares": [
                    {"user_id": u1_id, "split_method": "equal", "input_value": 0},
                    {"user_id": u2_id, "split_method": "equal", "input_value": 0},
                ],
            },
            {
                "title": "Cerveja", "amount": 30.0, "quantity": 3, "unit_amount": 10.0,
                "position": 1,
                "shares": [
                    {"user_id": u2_id, "split_method": "fixed", "input_value": 30.0},
                ],
            },
        ],
    }


def _post(ws_id, payload, headers):
    return client.post(f"/api/v1/workspaces/{ws_id}/transactions/", json=payload, headers=headers)


def _put(ws_id, tx_id, payload, headers):
    return client.put(f"/api/v1/workspaces/{ws_id}/transactions/{tx_id}", json=payload, headers=headers)


# ---------- criação em modo item ----------

def test_create_item_mode_derives_splits(two_member_ws, override_get_session):
    ws1, u1, u2 = two_member_ws["ws1"], two_member_ws["u1"], two_member_ws["u2"]
    resp = _post(ws1.id, _item_mode_payload(u1.id, u2.id), two_member_ws["headers1"])
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["split_mode"] == "item"
    splits = {s["user_id"]: s for s in data["splits"]}
    assert float(splits[u1.id]["computed_amount"]) == 30.0
    assert float(splits[u2.id]["computed_amount"]) == 60.0

    carne = next(i for i in data["items"] if i["title"] == "Carne")
    assert {float(sh["computed_amount"]) for sh in carne["shares"]} == {30.0}
    cerveja = next(i for i in data["items"] if i["title"] == "Cerveja")
    assert float(cerveja["quantity"]) == 3
    assert float(cerveja["unit_amount"]) == 10.0


def test_legacy_payload_still_works(two_member_ws, override_get_session):
    """Payload antigo (sem split_mode/payment_method/shares) segue idêntico."""
    ws1, u1 = two_member_ws["ws1"], two_member_ws["u1"]
    resp = _post(ws1.id, _base_payload(u1.id), two_member_ws["headers1"])
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["split_mode"] == "transaction"
    assert data["payment_method"] is None


# ---------- matriz de erros ----------

def test_items_sum_must_match_total(two_member_ws, override_get_session):
    ws1, u1, u2 = two_member_ws["ws1"], two_member_ws["u1"], two_member_ws["u2"]
    payload = _item_mode_payload(u1.id, u2.id)
    payload["items"][0]["amount"] = 50.0  # 50 + 30 != 90
    resp = _post(ws1.id, payload, two_member_ws["headers1"])
    assert resp.status_code == 400
    assert "Soma dos itens" in resp.json()["error"]["message"]


def test_item_percent_must_sum_100(two_member_ws, override_get_session):
    ws1, u1, u2 = two_member_ws["ws1"], two_member_ws["u1"], two_member_ws["u2"]
    payload = _item_mode_payload(u1.id, u2.id)
    payload["items"][0]["shares"] = [
        {"user_id": u1.id, "split_method": "percentage", "input_value": 50},
        {"user_id": u2.id, "split_method": "percentage", "input_value": 30},
    ]
    resp = _post(ws1.id, payload, two_member_ws["headers1"])
    assert resp.status_code == 400
    assert "Percentuais do item 'Carne'" in resp.json()["error"]["message"]


def test_item_fixed_must_match_item_amount(two_member_ws, override_get_session):
    ws1, u1, u2 = two_member_ws["ws1"], two_member_ws["u1"], two_member_ws["u2"]
    payload = _item_mode_payload(u1.id, u2.id)
    payload["items"][1]["shares"] = [
        {"user_id": u2.id, "split_method": "fixed", "input_value": 25.0},
    ]
    resp = _post(ws1.id, payload, two_member_ws["headers1"])
    assert resp.status_code == 400
    assert "Valores fixos do item 'Cerveja'" in resp.json()["error"]["message"]


def test_item_mode_without_items_rejected(two_member_ws, override_get_session):
    ws1, u1 = two_member_ws["ws1"], two_member_ws["u1"]
    payload = _base_payload(u1.id, split_mode="item", splits=[])
    resp = _post(ws1.id, payload, two_member_ws["headers1"])
    assert resp.status_code == 422  # estrutural: barrado no Pydantic


def test_quantity_times_unit_must_match_line(two_member_ws, override_get_session):
    ws1, u1, u2 = two_member_ws["ws1"], two_member_ws["u1"], two_member_ws["u2"]
    payload = _item_mode_payload(u1.id, u2.id)
    payload["items"][1]["unit_amount"] = 9.0  # 3 × 9 != 30
    resp = _post(ws1.id, payload, two_member_ws["headers1"])
    assert resp.status_code == 422


def test_duplicate_split_user_rejected(two_member_ws, override_get_session):
    ws1, u1 = two_member_ws["ws1"], two_member_ws["u1"]
    payload = _base_payload(u1.id, splits=[
        {"user_id": u1.id, "split_method": "equal", "input_value": 0},
        {"user_id": u1.id, "split_method": "equal", "input_value": 0},
    ])
    resp = _post(ws1.id, payload, two_member_ws["headers1"])
    assert resp.status_code == 422


def test_split_user_must_be_member(two_member_ws, override_get_session):
    ws1, u1 = two_member_ws["ws1"], two_member_ws["u1"]
    payload = _base_payload(u1.id, splits=[
        {"user_id": 99999, "split_method": "equal", "input_value": 0},
    ])
    resp = _post(ws1.id, payload, two_member_ws["headers1"])
    assert resp.status_code == 400
    assert "não pertence" in resp.json()["error"]["message"]


def test_credit_card_method_requires_card(two_member_ws, override_get_session):
    ws1, u1 = two_member_ws["ws1"], two_member_ws["u1"]
    payload = _base_payload(u1.id, payment_method="credit_card")
    resp = _post(ws1.id, payload, two_member_ws["headers1"])
    assert resp.status_code == 422


# ---------- método de pagamento ----------

def test_payment_method_persisted_and_filterable(two_member_ws, override_get_session):
    ws1, u1 = two_member_ws["ws1"], two_member_ws["u1"]
    headers = two_member_ws["headers1"]

    resp = _post(ws1.id, _base_payload(u1.id, title="Pix Tx", payment_method="pix"), headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["payment_method"] == "pix"

    resp = _post(ws1.id, _base_payload(u1.id, title="Cash Tx", payment_method="cash"), headers)
    assert resp.status_code == 200

    resp = client.get(
        f"/api/v1/workspaces/{ws1.id}/transactions/?payment_method=pix", headers=headers
    )
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "Pix Tx"


# ---------- edição completa ----------

def test_full_edit_replaces_children_atomically(db_session, two_member_ws, override_get_session):
    ws1, u1, u2 = two_member_ws["ws1"], two_member_ws["u1"], two_member_ws["u2"]
    headers = two_member_ws["headers1"]

    tx_id = _post(ws1.id, _base_payload(u1.id), headers).json()["id"]

    resp = _put(ws1.id, tx_id, {
        "total_amount": 90.0,
        "payers": [{"user_id": u1.id, "amount": 90.0}],
        "splits": [
            {"user_id": u1.id, "split_method": "percentage", "input_value": 70},
            {"user_id": u2.id, "split_method": "percentage", "input_value": 30},
        ],
    }, headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    splits = {s["user_id"]: float(s["computed_amount"]) for s in data["splits"]}
    assert splits == {u1.id: 63.0, u2.id: 27.0}

    # Sem filhos órfãos no banco
    db_splits = db_session.exec(
        select(TransactionSplit).where(TransactionSplit.transaction_id == tx_id)
    ).all()
    assert len(db_splits) == 2


def test_full_edit_can_switch_to_item_mode(two_member_ws, override_get_session):
    ws1, u1, u2 = two_member_ws["ws1"], two_member_ws["u1"], two_member_ws["u2"]
    headers = two_member_ws["headers1"]

    tx_id = _post(ws1.id, _base_payload(u1.id), headers).json()["id"]
    item_payload = _item_mode_payload(u1.id, u2.id)

    resp = _put(ws1.id, tx_id, {
        "total_amount": 90.0,
        "split_mode": "item",
        "payers": item_payload["payers"],
        "splits": [],
        "items": item_payload["items"],
    }, headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["split_mode"] == "item"
    assert len(data["items"]) == 2
    splits = {s["user_id"]: float(s["computed_amount"]) for s in data["splits"]}
    assert splits == {u1.id: 30.0, u2.id: 60.0}


def test_full_edit_invalid_keeps_old_children(db_session, two_member_ws, override_get_session):
    ws1, u1, u2 = two_member_ws["ws1"], two_member_ws["u1"], two_member_ws["u2"]
    headers = two_member_ws["headers1"]

    tx_id = _post(ws1.id, _base_payload(u1.id), headers).json()["id"]

    resp = _put(ws1.id, tx_id, {
        "payers": [{"user_id": u1.id, "amount": 90.0}],
        "splits": [
            {"user_id": u1.id, "split_method": "percentage", "input_value": 60},
            {"user_id": u2.id, "split_method": "percentage", "input_value": 30},
        ],
    }, headers)
    assert resp.status_code == 400

    # Rollback preservou os filhos originais
    db_session.expire_all()
    payers = db_session.exec(
        select(TransactionPayer).where(TransactionPayer.transaction_id == tx_id)
    ).all()
    splits = db_session.exec(
        select(TransactionSplit).where(TransactionSplit.transaction_id == tx_id)
    ).all()
    assert len(payers) == 1
    assert len(splits) == 1
    assert splits[0].split_method.value == "equal"


def test_full_edit_requires_complete_set(two_member_ws, override_get_session):
    ws1, u1, u2 = two_member_ws["ws1"], two_member_ws["u1"], two_member_ws["u2"]
    headers = two_member_ws["headers1"]

    tx_id = _post(ws1.id, _base_payload(u1.id), headers).json()["id"]

    resp = _put(ws1.id, tx_id, {
        "splits": [{"user_id": u2.id, "split_method": "equal", "input_value": 0}],
    }, headers)
    assert resp.status_code == 400
    assert "conjunto completo" in resp.json()["error"]["message"]


def test_partial_total_change_blocked_for_item_mode(two_member_ws, override_get_session):
    ws1, u1, u2 = two_member_ws["ws1"], two_member_ws["u1"], two_member_ws["u2"]
    headers = two_member_ws["headers1"]

    tx_id = _post(ws1.id, _item_mode_payload(u1.id, u2.id), headers).json()["id"]

    resp = _put(ws1.id, tx_id, {"total_amount": 120.0}, headers)
    assert resp.status_code == 400
    assert "itens" in resp.json()["error"]["message"]


# ---------- trava de paga ----------

def test_paid_transaction_locked_until_reopened(two_member_ws, override_get_session):
    ws1, u1 = two_member_ws["ws1"], two_member_ws["u1"]
    headers = two_member_ws["headers1"]

    tx_id = _post(ws1.id, _base_payload(u1.id), headers).json()["id"]

    assert _put(ws1.id, tx_id, {"status": "paid"}, headers).status_code == 200

    resp = _put(ws1.id, tx_id, {"title": "Novo título"}, headers)
    assert resp.status_code == 409
    assert "reabra" in resp.json()["error"]["message"]

    resp = client.delete(
        f"/api/v1/workspaces/{ws1.id}/transactions/{tx_id}", headers=headers
    )
    assert resp.status_code == 409

    # Reabrir (só status) e editar de novo
    assert _put(ws1.id, tx_id, {"status": "confirmed"}, headers).status_code == 200
    assert _put(ws1.id, tx_id, {"title": "Novo título"}, headers).status_code == 200


# ---------- auditoria / eventos ----------

def test_full_edit_publishes_event_and_audit(db_session, two_member_ws, override_get_session):
    from app.models.sync_event import SyncEvent
    from app.models.audit import AuditLog

    ws1, u1, u2 = two_member_ws["ws1"], two_member_ws["u1"], two_member_ws["u2"]
    headers = two_member_ws["headers1"]

    tx_id = _post(ws1.id, _base_payload(u1.id), headers).json()["id"]

    resp = _put(ws1.id, tx_id, {
        "payers": [{"user_id": u1.id, "amount": 90.0}],
        "splits": [
            {"user_id": u1.id, "split_method": "fixed", "input_value": 40.0},
            {"user_id": u2.id, "split_method": "fixed", "input_value": 50.0},
        ],
    }, headers)
    assert resp.status_code == 200, resp.text

    events = db_session.exec(
        select(SyncEvent).where(
            SyncEvent.workspace_id == ws1.id,
            SyncEvent.event_type == "transaction.updated",
        )
    ).all()
    assert len(events) >= 1

    audit = db_session.exec(
        select(AuditLog).where(AuditLog.resource_type == "TransactionSplit")
    ).all()
    assert any(a.action.value == "delete" for a in audit)
    assert any(a.action.value == "create" for a in audit)
