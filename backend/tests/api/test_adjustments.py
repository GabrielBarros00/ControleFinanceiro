"""Ajustes de total: total = soma(itens) + soma(ajustes), com rateio
proporcional em centavos nos splits derivados do modo item."""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.models.transaction import Transaction, TransactionAdjustment, TransactionSplit
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


def _item_mode_payload(u1_id, u2_id, **overrides):
    """Item 1 (60) só do u1; item 2 (40) só do u2; desconto de -10 → total 90."""
    payload = {
        "title": "Compra com desconto",
        "total_amount": 90.0,
        "transaction_date": "2026-06-10T12:00:00",
        "split_mode": "item",
        "payers": [{"user_id": u1_id, "amount": 90.0}],
        "splits": [],
        "items": [
            {"title": "Carne", "amount": 60.0,
             "shares": [{"user_id": u1_id, "split_method": "equal", "input_value": 0}]},
            {"title": "Bebidas", "amount": 40.0,
             "shares": [{"user_id": u2_id, "split_method": "equal", "input_value": 0}]},
        ],
        "adjustments": [
            {"type": "discount", "description": "Cupom", "amount": -10.0},
        ],
    }
    payload.update(overrides)
    return payload


def test_ajuste_com_rateio_proporcional_no_modo_item(db_session, two_member_ws, override_get_session):
    ws1, u1, u2 = two_member_ws["ws1"], two_member_ws["u1"], two_member_ws["u2"]

    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        json=_item_mode_payload(u1.id, u2.id),
        headers=two_member_ws["headers1"],
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert len(data["adjustments"]) == 1
    assert data["adjustments"][0]["type"] == "discount"

    # Desconto de 10 rateado 6/4 (proporcional a 60/40): u1 fica 54, u2 fica 36
    splits = {s["user_id"]: Decimal(s["computed_amount"]) for s in data["splits"]}
    assert splits == {u1.id: Decimal("54.00"), u2.id: Decimal("36.00")}
    assert sum(splits.values()) == Decimal("90.00")


def test_itens_mais_ajustes_precisam_fechar_o_total(two_member_ws, override_get_session):
    ws1, u1, u2 = two_member_ws["ws1"], two_member_ws["u1"], two_member_ws["u2"]

    payload = _item_mode_payload(
        u1.id, u2.id,
        total_amount=95.0,  # 100 - 10 ≠ 95
        payers=[{"user_id": u1.id, "amount": 95.0}],
    )
    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        json=payload,
        headers=two_member_ws["headers1"],
    )
    assert resp.status_code == 400
    assert "não fecham o total" in resp.json()["error"]["message"]


def test_ajuste_sem_itens_e_rejeitado(two_member_ws, override_get_session):
    ws1, u1 = two_member_ws["ws1"], two_member_ws["u1"]
    payload = {
        "title": "Sem itens",
        "total_amount": 90.0,
        "transaction_date": "2026-06-10T12:00:00",
        "payers": [{"user_id": u1.id, "amount": 90.0}],
        "splits": [{"user_id": u1.id, "split_method": "equal", "input_value": 0}],
        "adjustments": [{"type": "discount", "amount": -10.0}],
    }
    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        json=payload,
        headers=two_member_ws["headers1"],
    )
    assert resp.status_code == 422


def test_sinal_por_tipo_e_validado(two_member_ws, override_get_session):
    ws1, u1, u2 = two_member_ws["ws1"], two_member_ws["u1"], two_member_ws["u2"]

    payload = _item_mode_payload(u1.id, u2.id, total_amount=110.0)
    payload["adjustments"] = [{"type": "discount", "amount": 10.0}]  # desconto positivo
    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        json=payload,
        headers=two_member_ws["headers1"],
    )
    assert resp.status_code == 422

    payload["adjustments"] = [{"type": "shipping", "amount": -10.0}]  # frete negativo
    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        json=payload,
        headers=two_member_ws["headers1"],
    )
    assert resp.status_code == 422


def test_frete_no_modo_transaction_com_item_categoria(two_member_ws, override_get_session):
    """Ajuste positivo no modo transaction: itens (100) + frete (12) = 112."""
    ws1, u1 = two_member_ws["ws1"], two_member_ws["u1"]
    payload = {
        "title": "Compra online",
        "total_amount": 112.0,
        "transaction_date": "2026-06-10T12:00:00",
        "payers": [{"user_id": u1.id, "amount": 112.0}],
        "splits": [{"user_id": u1.id, "split_method": "equal", "input_value": 0}],
        "items": [{"title": "Tênis", "amount": 100.0}],
        "adjustments": [{"type": "shipping", "description": "Sedex", "amount": 12.0}],
    }
    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        json=payload,
        headers=two_member_ws["headers1"],
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert Decimal(data["splits"][0]["computed_amount"]) == Decimal("112.00")


def test_edicao_completa_sem_campo_descarta_ajustes(db_session, two_member_ws, override_get_session):
    ws1, u1, u2 = two_member_ws["ws1"], two_member_ws["u1"], two_member_ws["u2"]
    headers = two_member_ws["headers1"]

    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        json=_item_mode_payload(u1.id, u2.id),
        headers=headers,
    )
    tx_id = resp.json()["id"]

    # Edição completa SEM adjustments: itens precisam fechar o total sozinhos
    resp = client.put(
        f"/api/v1/workspaces/{ws1.id}/transactions/{tx_id}",
        json={
            "total_amount": 100.0,
            "split_mode": "item",
            "payers": [{"user_id": u1.id, "amount": 100.0}],
            "items": [
                {"title": "Carne", "amount": 60.0,
                 "shares": [{"user_id": u1.id, "split_method": "equal", "input_value": 0}]},
                {"title": "Bebidas", "amount": 40.0,
                 "shares": [{"user_id": u2.id, "split_method": "equal", "input_value": 0}]},
            ],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    assert db_session.exec(
        select(TransactionAdjustment).where(TransactionAdjustment.transaction_id == tx_id)
    ).all() == []
    splits = db_session.exec(
        select(TransactionSplit).where(TransactionSplit.transaction_id == tx_id)
    ).all()
    assert sum(s.computed_amount for s in splits) == Decimal("100.00")


def test_caminho_parcial_bloqueado_com_ajustes(two_member_ws, override_get_session):
    ws1, u1 = two_member_ws["ws1"], two_member_ws["u1"]
    headers = two_member_ws["headers1"]
    payload = {
        "title": "Compra online",
        "total_amount": 112.0,
        "transaction_date": "2026-06-10T12:00:00",
        "payers": [{"user_id": u1.id, "amount": 112.0}],
        "splits": [{"user_id": u1.id, "split_method": "equal", "input_value": 0}],
        "items": [{"title": "Tênis", "amount": 100.0}],
        "adjustments": [{"type": "shipping", "amount": 12.0}],
    }
    resp = client.post(f"/api/v1/workspaces/{ws1.id}/transactions/", json=payload, headers=headers)
    tx_id = resp.json()["id"]

    resp = client.put(
        f"/api/v1/workspaces/{ws1.id}/transactions/{tx_id}",
        json={"total_amount": 120.0},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "edição completa" in resp.json()["error"]["message"]


def test_preview_calcula_sem_persistir(db_session, two_member_ws, override_get_session):
    ws1, u1, u2 = two_member_ws["ws1"], two_member_ws["u1"], two_member_ws["u2"]

    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/preview",
        json=_item_mode_payload(u1.id, u2.id),
        headers=two_member_ws["headers1"],
    )
    assert resp.status_code == 200, resp.text
    breakdown = resp.json()
    splits = {s["user_id"]: Decimal(str(s["computed_amount"])) for s in breakdown["splits"]}
    assert splits == {u1.id: Decimal("54.00"), u2.id: Decimal("36.00")}

    # Nada persistido
    db_session.expire_all()
    assert db_session.exec(
        select(Transaction).where(Transaction.workspace_id == ws1.id)
    ).all() == []

    # Preview inválido → 400 com a mesma mensagem do POST real
    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/preview",
        json=_item_mode_payload(u1.id, u2.id, total_amount=95.0),
        headers=two_member_ws["headers1"],
    )
    assert resp.status_code == 400
