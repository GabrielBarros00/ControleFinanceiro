"""Coesão do grupo de parcelamento: cancelar/excluir todas as irmãs de uma vez,
preservando parcelas já pagas (ADR 0003/0011)."""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.models.credit_card import CreditCard
from app.models.transaction import Transaction, TransactionStatus

client = TestClient(app)


@pytest.fixture(name="setup_data")
def setup_data_with_card(db_session: Session, setup_data):
    card = CreditCard(
        workspace_id=setup_data["ws1"].id, name="Card",
        limit=Decimal("50000.00"), closing_day=25, due_day=5,
    )
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    setup_data["card"] = card
    return setup_data


def _create_installments(ws_id, headers, user_id, card_id, count=3):
    return client.post(
        f"/api/v1/workspaces/{ws_id}/transactions/",
        json={
            "title": "Geladeira",
            "total_amount": 300.0,
            "transaction_date": "2026-01-10T12:00:00",
            "installments_count": count,
            "credit_card_id": card_id,
            "payment_method": "credit_card",
            "payers": [{"user_id": user_id, "amount": 300.0}],
            "splits": [{"user_id": user_id, "split_method": "equal", "input_value": 0}],
        },
        headers=headers,
    )


def _group(db_session, ws_id):
    return db_session.exec(
        select(Transaction).where(
            Transaction.workspace_id == ws_id,
            Transaction.installment_group_id.is_not(None),
        )
    ).all()


def test_cancelar_grupo_inteiro(db_session, setup_data, override_get_session):
    ws, u1, headers = setup_data["ws1"], setup_data["u1"], setup_data["headers1"]
    resp = _create_installments(ws.id, headers, u1.id, setup_data["card"].id, 3)
    anchor_id = resp.json()["id"]

    resp = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/{anchor_id}/installment-group/cancel",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["cancelled"] == 3
    db_session.expire_all()
    for tx in _group(db_session, ws.id):
        assert tx.status == TransactionStatus.cancelled
        assert tx.cancelled_at is not None


def test_excluir_grupo_inteiro(db_session, setup_data, override_get_session):
    ws, u1, headers = setup_data["ws1"], setup_data["u1"], setup_data["headers1"]
    resp = _create_installments(ws.id, headers, u1.id, setup_data["card"].id, 3)
    anchor_id = resp.json()["id"]

    resp = client.delete(
        f"/api/v1/workspaces/{ws.id}/transactions/{anchor_id}/installment-group",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] == 3
    db_session.expire_all()
    alive = db_session.exec(
        select(Transaction).where(
            Transaction.workspace_id == ws.id,
            Transaction.installment_group_id.is_not(None),
            Transaction.deleted_at.is_(None),
        )
    ).all()
    assert alive == []


def test_parcela_paga_e_preservada_ao_excluir_grupo(db_session, setup_data, override_get_session):
    ws, u1, headers = setup_data["ws1"], setup_data["u1"], setup_data["headers1"]
    resp = _create_installments(ws.id, headers, u1.id, setup_data["card"].id, 3)
    anchor_id = resp.json()["id"]

    # Paga a primeira parcela (confirmed → paid)
    resp = client.put(
        f"/api/v1/workspaces/{ws.id}/transactions/{anchor_id}",
        json={"status": "paid"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    resp = client.delete(
        f"/api/v1/workspaces/{ws.id}/transactions/{anchor_id}/installment-group",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deleted"] == 2
    assert body["skipped_paid"] == 1
    db_session.expire_all()
    paid = db_session.get(Transaction, anchor_id)
    assert paid.status == TransactionStatus.paid
    assert paid.deleted_at is None


def test_membro_nao_cancela_grupo_de_outro(db_session, setup_data, override_get_session):
    """u2 não é membro do ws1 → 403/404 ao tentar mexer no grupo alheio."""
    ws, u1, headers1 = setup_data["ws1"], setup_data["u1"], setup_data["headers1"]
    resp = _create_installments(ws.id, headers1, u1.id, setup_data["card"].id, 2)
    anchor_id = resp.json()["id"]

    resp = client.delete(
        f"/api/v1/workspaces/{ws.id}/transactions/{anchor_id}/installment-group",
        headers=setup_data["headers2"],
    )
    assert resp.status_code in (403, 404)
