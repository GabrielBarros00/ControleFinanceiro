"""Edição da compra parcelada INTEIRA (PUT .../installment-group): refatiar
total/nº de parcelas quando não há pagas; congelar pagas e recalcular só as
abertas quando há; 409 nos casos que corromperiam o histórico."""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.models.credit_card import CreditCard
from app.models.transaction import Transaction, TransactionStatus
from app.models.workspace import WorkspaceMembership, WorkspaceRole

client = TestClient(app)


@pytest.fixture(name="setup_data")
def setup_data_with_card(db_session: Session, setup_data):
    # u2 vira membro do ws1 para os testes de divisão fixa entre duas pessoas
    db_session.add(WorkspaceMembership(
        workspace_id=setup_data["ws1"].id, user_id=setup_data["u2"].id, role=WorkspaceRole.member,
    ))
    card = CreditCard(
        workspace_id=setup_data["ws1"].id, name="Card",
        limit=Decimal("50000.00"), closing_day=25, due_day=5,
    )
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    setup_data["card"] = card
    return setup_data


def _create(ws_id, headers, user_id, card_id, total=300.0, count=3):
    return client.post(
        f"/api/v1/workspaces/{ws_id}/transactions/",
        json={
            "title": "Geladeira",
            "total_amount": total,
            "transaction_date": "2026-01-10T12:00:00",
            "installments_count": count,
            "credit_card_id": card_id,
            "payment_method": "credit_card",
            "payers": [{"user_id": user_id, "amount": total}],
            "splits": [{"user_id": user_id, "split_method": "equal", "input_value": 0}],
        },
        headers=headers,
    )


def _edit_body(user_id, card_id, total, count, **overrides):
    body = {
        "title": "Geladeira",
        "total_amount": total,
        "transaction_date": "2026-01-10T12:00:00",
        "installments_count": count,
        "credit_card_id": card_id,
        "payment_method": "credit_card",
        "payers": [{"user_id": user_id, "amount": total}],
        "splits": [{"user_id": user_id, "split_method": "equal", "input_value": 0}],
    }
    body.update(overrides)
    return body


def _live_group(db_session, ws_id, group_id):
    return db_session.exec(
        select(Transaction).where(
            Transaction.workspace_id == ws_id,
            Transaction.installment_group_id == group_id,
            Transaction.deleted_at.is_(None),
        ).order_by(Transaction.installment_no)
    ).all()


def test_group_edit_muda_total_refatia(db_session, setup_data, override_get_session):
    ws, u1, headers, card = setup_data["ws1"], setup_data["u1"], setup_data["headers1"], setup_data["card"]
    resp = _create(ws.id, headers, u1.id, card.id, total=300.0, count=3)
    anchor_id, group_id = resp.json()["id"], resp.json()["installment_group_id"]

    resp = client.put(
        f"/api/v1/workspaces/{ws.id}/transactions/{anchor_id}/installment-group",
        json=_edit_body(u1.id, card.id, total=600.0, count=3),
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    live = _live_group(db_session, ws.id, group_id)
    assert len(live) == 3
    assert [tx.total_amount for tx in live] == [Decimal("200.00"), Decimal("200.00"), Decimal("200.00")]
    assert sum(tx.total_amount for tx in live) == Decimal("600.00")
    assert [tx.title for tx in live] == ["Geladeira (1/3)", "Geladeira (2/3)", "Geladeira (3/3)"]


def test_group_edit_muda_numero_de_parcelas(db_session, setup_data, override_get_session):
    ws, u1, headers, card = setup_data["ws1"], setup_data["u1"], setup_data["headers1"], setup_data["card"]
    resp = _create(ws.id, headers, u1.id, card.id, total=300.0, count=3)
    anchor_id, group_id = resp.json()["id"], resp.json()["installment_group_id"]

    resp = client.put(
        f"/api/v1/workspaces/{ws.id}/transactions/{anchor_id}/installment-group",
        json=_edit_body(u1.id, card.id, total=300.0, count=6),
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    live = _live_group(db_session, ws.id, group_id)
    assert len(live) == 6
    assert all(tx.installments_of == 6 for tx in live)
    assert [tx.total_amount for tx in live] == [Decimal("50.00")] * 6
    assert [tx.billing_month for tx in live] == [
        "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06",
    ]


def test_group_edit_metadata_aplica_a_todas(db_session, setup_data, override_get_session):
    ws, u1, headers, card = setup_data["ws1"], setup_data["u1"], setup_data["headers1"], setup_data["card"]
    resp = _create(ws.id, headers, u1.id, card.id, total=300.0, count=3)
    anchor_id, group_id = resp.json()["id"], resp.json()["installment_group_id"]

    resp = client.put(
        f"/api/v1/workspaces/{ws.id}/transactions/{anchor_id}/installment-group",
        json=_edit_body(u1.id, card.id, total=300.0, count=3, title="Freezer"),
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    live = _live_group(db_session, ws.id, group_id)
    assert [tx.title for tx in live] == ["Freezer (1/3)", "Freezer (2/3)", "Freezer (3/3)"]


def test_group_edit_com_paga_recalcula_apenas_abertas(db_session, setup_data, override_get_session):
    ws, u1, headers, card = setup_data["ws1"], setup_data["u1"], setup_data["headers1"], setup_data["card"]
    resp = _create(ws.id, headers, u1.id, card.id, total=300.0, count=3)
    anchor_id, group_id = resp.json()["id"], resp.json()["installment_group_id"]

    # Paga a 1ª parcela (100.00)
    resp = client.put(
        f"/api/v1/workspaces/{ws.id}/transactions/{anchor_id}",
        json={"status": "paid"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    # Novo total 330: pago 100 fica congelado; 230 restantes fatiados entre as 2 abertas
    resp = client.put(
        f"/api/v1/workspaces/{ws.id}/transactions/{anchor_id}/installment-group",
        json=_edit_body(u1.id, card.id, total=330.0, count=3),
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    live = _live_group(db_session, ws.id, group_id)
    assert len(live) == 3
    paid = db_session.get(Transaction, anchor_id)
    assert paid.status == TransactionStatus.paid
    assert paid.total_amount == Decimal("100.00")  # congelada
    abertas = [tx for tx in live if tx.id != anchor_id]
    assert [tx.total_amount for tx in abertas] == [Decimal("115.00"), Decimal("115.00")]
    assert sum(tx.total_amount for tx in live) == Decimal("330.00")


def test_group_edit_reduz_abaixo_do_pago_409(db_session, setup_data, override_get_session):
    ws, u1, headers, card = setup_data["ws1"], setup_data["u1"], setup_data["headers1"], setup_data["card"]
    resp = _create(ws.id, headers, u1.id, card.id, total=300.0, count=3)
    anchor_id = resp.json()["id"]
    client.put(f"/api/v1/workspaces/{ws.id}/transactions/{anchor_id}", json={"status": "paid"}, headers=headers)

    resp = client.put(
        f"/api/v1/workspaces/{ws.id}/transactions/{anchor_id}/installment-group",
        json=_edit_body(u1.id, card.id, total=90.0, count=3),
        headers=headers,
    )
    assert resp.status_code == 409, resp.text


def test_group_edit_muda_nº_parcelas_com_paga_409(db_session, setup_data, override_get_session):
    ws, u1, headers, card = setup_data["ws1"], setup_data["u1"], setup_data["headers1"], setup_data["card"]
    resp = _create(ws.id, headers, u1.id, card.id, total=300.0, count=3)
    anchor_id = resp.json()["id"]
    client.put(f"/api/v1/workspaces/{ws.id}/transactions/{anchor_id}", json={"status": "paid"}, headers=headers)

    resp = client.put(
        f"/api/v1/workspaces/{ws.id}/transactions/{anchor_id}/installment-group",
        json=_edit_body(u1.id, card.id, total=300.0, count=4),
        headers=headers,
    )
    assert resp.status_code == 409, resp.text


def test_group_summary(db_session, setup_data, override_get_session):
    ws, u1, headers, card = setup_data["ws1"], setup_data["u1"], setup_data["headers1"], setup_data["card"]
    resp = _create(ws.id, headers, u1.id, card.id, total=300.0, count=3)
    anchor_id = resp.json()["id"]

    resp = client.get(
        f"/api/v1/workspaces/{ws.id}/transactions/{anchor_id}/installment-group",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["installments_of"] == 3
    assert body["count_live"] == 3
    assert body["paid_count"] == 0
    assert Decimal(str(body["group_total"])) == Decimal("300.00")
    assert body["title"] == "Geladeira"
    # A definição inteira (whole) traz o total cheio e as parcelas p/ o form
    whole = body["whole"]
    assert whole["total_amount"] == "300.00"
    assert whole["installments_of"] == 3
    assert whole["title"] == "Geladeira"


def test_group_summary_whole_soma_splits_fixos(db_session, setup_data, override_get_session):
    """whole agrega valor fixo SOMANDO entre as parcelas — senão a divisão não
    fecharia o total cheio ao pré-preencher o form."""
    ws, u1, u2, headers, card = (
        setup_data["ws1"], setup_data["u1"], setup_data["u2"], setup_data["headers1"], setup_data["card"],
    )
    resp = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/",
        json={
            "title": "Sofá", "total_amount": 100.0, "transaction_date": "2026-01-10T12:00:00",
            "installments_count": 2, "credit_card_id": card.id, "payment_method": "credit_card",
            "payers": [{"user_id": u1.id, "amount": 100.0}],
            "splits": [
                {"user_id": u1.id, "split_method": "fixed", "input_value": 60.0},
                {"user_id": u2.id, "split_method": "fixed", "input_value": 40.0},
            ],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    anchor_id = resp.json()["id"]

    resp = client.get(
        f"/api/v1/workspaces/{ws.id}/transactions/{anchor_id}/installment-group",
        headers=headers,
    )
    whole = resp.json()["whole"]
    assert whole["total_amount"] == "100.00"
    splits = {s["user_id"]: s["input_value"] for s in whole["splits"]}
    assert splits == {u1.id: "60.00", u2.id: "40.00"}


def test_group_edit_fixo_roundtrip(db_session, setup_data, override_get_session):
    """Edita compra com divisão fixa: novo total 200 (120/80) → 2 parcelas de
    100, cada uma 60/40."""
    ws, u1, u2, headers, card = (
        setup_data["ws1"], setup_data["u1"], setup_data["u2"], setup_data["headers1"], setup_data["card"],
    )
    resp = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/",
        json={
            "title": "Sofá", "total_amount": 100.0, "transaction_date": "2026-01-10T12:00:00",
            "installments_count": 2, "credit_card_id": card.id, "payment_method": "credit_card",
            "payers": [{"user_id": u1.id, "amount": 100.0}],
            "splits": [
                {"user_id": u1.id, "split_method": "fixed", "input_value": 60.0},
                {"user_id": u2.id, "split_method": "fixed", "input_value": 40.0},
            ],
        },
        headers=headers,
    )
    anchor_id, group_id = resp.json()["id"], resp.json()["installment_group_id"]

    resp = client.put(
        f"/api/v1/workspaces/{ws.id}/transactions/{anchor_id}/installment-group",
        json={
            "title": "Sofá", "total_amount": 200.0, "transaction_date": "2026-01-10T12:00:00",
            "installments_count": 2, "credit_card_id": card.id, "payment_method": "credit_card",
            "payers": [{"user_id": u1.id, "amount": 200.0}],
            "splits": [
                {"user_id": u1.id, "split_method": "fixed", "input_value": 120.0},
                {"user_id": u2.id, "split_method": "fixed", "input_value": 80.0},
            ],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    first = resp.json()
    # 1ª parcela: 100 no total, 60/40
    assert first["total_amount"] == "100.00"
    splits = {s["user_id"]: s["computed_amount"] for s in first["splits"]}
    assert splits == {u1.id: "60.00", u2.id: "40.00"}

    db_session.expire_all()
    live = _live_group(db_session, ws.id, group_id)
    assert [tx.total_amount for tx in live] == [Decimal("100.00"), Decimal("100.00")]


def test_group_edit_nao_parcelado_400(db_session, setup_data, override_get_session):
    """PUT installment-group num lançamento comum (sem grupo) → 400."""
    ws, u1, headers, card = setup_data["ws1"], setup_data["u1"], setup_data["headers1"], setup_data["card"]
    resp = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/",
        json={
            "title": "Compra à vista",
            "total_amount": 100.0,
            "transaction_date": "2026-01-10T12:00:00",
            "credit_card_id": card.id,
            "payment_method": "credit_card",
            "payers": [{"user_id": u1.id, "amount": 100.0}],
            "splits": [{"user_id": u1.id, "split_method": "equal", "input_value": 0}],
        },
        headers=headers,
    )
    tx_id = resp.json()["id"]
    resp = client.put(
        f"/api/v1/workspaces/{ws.id}/transactions/{tx_id}/installment-group",
        json=_edit_body(u1.id, card.id, total=100.0, count=2),
        headers=headers,
    )
    assert resp.status_code == 400, resp.text
