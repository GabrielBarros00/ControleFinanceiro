"""Parcelamento no cartão: N transações irmãs em meses/faturas sucessivos."""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.models.credit_card import CreditCard, CardStatement
from app.models.transaction import Transaction
from app.models.workspace import WorkspaceMembership, WorkspaceRole

client = TestClient(app)


@pytest.fixture(name="ws_with_card")
def ws_with_card_fixture(db_session: Session, setup_data):
    db_session.add(WorkspaceMembership(
        workspace_id=setup_data["ws1"].id,
        user_id=setup_data["u2"].id,
        role=WorkspaceRole.member,
    ))
    card = CreditCard(
        name="Nubank",
        limit=Decimal("5000.00"),
        closing_day=25,
        due_day=5, owner_user_id=setup_data["u1"].id)
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    setup_data["card"] = card
    return setup_data


def _payload(u1_id, card_id, **overrides):
    payload = {
        "title": "Notebook",
        "total_amount": 100.0,
        "transaction_date": "2026-01-15T12:00:00",
        "credit_card_id": card_id,
        "payment_method": "credit_card",
        "installments_count": 3,
        "payers": [{"user_id": u1_id, "amount": 100.0}],
        "splits": [{"user_id": u1_id, "split_method": "equal", "input_value": 0}],
    }
    payload.update(overrides)
    return payload


def test_installments_create_sibling_transactions(db_session, ws_with_card, override_get_session):
    ws1, u1, card = ws_with_card["ws1"], ws_with_card["u1"], ws_with_card["card"]
    headers = ws_with_card["headers1"]

    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        json=_payload(u1.id, card.id),
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    first = resp.json()
    assert first["title"] == "Notebook (1/3)"
    assert first["installment_no"] == 1
    assert first["installments_of"] == 3
    assert first["installment_group_id"]

    siblings = db_session.exec(
        select(Transaction).where(
            Transaction.installment_group_id == first["installment_group_id"]
        ).order_by(Transaction.installment_no)
    ).all()
    assert len(siblings) == 3
    assert [tx.billing_month for tx in siblings] == ["2026-01", "2026-02", "2026-03"]
    # Centavos: 100/3 = 33.34 + 33.33 + 33.33 (resíduo na primeira — ADR 0001)
    assert [tx.total_amount for tx in siblings] == [
        Decimal("33.34"), Decimal("33.33"), Decimal("33.33")
    ]
    assert sum(tx.total_amount for tx in siblings) == Decimal("100.00")

    # Cada parcela roteada para a fatura do seu mês
    statement_ids = {tx.statement_id for tx in siblings}
    assert None not in statement_ids
    assert len(statement_ids) == 3
    months = {
        db_session.get(CardStatement, sid).month for sid in statement_ids
    }
    assert len(months) == 3


def test_installments_with_percentage_split(db_session, ws_with_card, override_get_session):
    ws1, u1, u2, card = ws_with_card["ws1"], ws_with_card["u1"], ws_with_card["u2"], ws_with_card["card"]
    headers = ws_with_card["headers1"]

    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        json=_payload(u1.id, card.id, total_amount=90.0, installments_count=2, payers=[
            {"user_id": u1.id, "amount": 90.0},
        ], splits=[
            {"user_id": u1.id, "split_method": "percentage", "input_value": 50},
            {"user_id": u2.id, "split_method": "percentage", "input_value": 50},
        ]),
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    first = resp.json()
    # 45.00 por parcela → 22.50 para cada um
    splits = {s["user_id"]: s["computed_amount"] for s in first["splits"]}
    assert splits == {u1.id: "22.50", u2.id: "22.50"}


def test_installments_rollback_atomico_em_falha_no_meio_do_loop(
    db_session, ws_with_card, override_get_session, monkeypatch
):
    """TX-001: falha na parcela N descarta TUDO — inclusive parcelas anteriores
    e faturas criadas no caminho (nenhum commit interno no loop)."""
    import app.api.routes.transactions as tx_routes

    ws1, u1, card = ws_with_card["ws1"], ws_with_card["u1"], ws_with_card["card"]
    original = tx_routes.persist_transaction_children
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ValueError("falha simulada na parcela 2")
        return original(*args, **kwargs)

    monkeypatch.setattr(tx_routes, "persist_transaction_children", flaky)

    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        json=_payload(u1.id, card.id),
        headers=ws_with_card["headers1"],
    )
    assert resp.status_code == 400
    assert calls["n"] == 2

    db_session.expire_all()
    leftover_txs = db_session.exec(
        select(Transaction).where(Transaction.workspace_id == ws1.id)
    ).all()
    assert leftover_txs == []
    leftover_stmts = db_session.exec(
        select(CardStatement).where(CardStatement.card_id == card.id)
    ).all()
    assert leftover_stmts == []


def test_installments_validations(ws_with_card, override_get_session):
    ws1, u1, u2, card = ws_with_card["ws1"], ws_with_card["u1"], ws_with_card["u2"], ws_with_card["card"]
    headers = ws_with_card["headers1"]
    url = f"/api/v1/workspaces/{ws1.id}/transactions/"

    # Sem cartão de crédito
    resp = client.post(url, json=_payload(u1.id, card.id, credit_card_id=None, payment_method="pix"), headers=headers)
    assert resp.status_code == 422

    # Múltiplos pagadores (parcelamento exige um único pagador)
    resp = client.post(url, json=_payload(u1.id, card.id, payers=[
        {"user_id": u1.id, "amount": 50.0},
        {"user_id": u2.id, "amount": 50.0},
    ]), headers=headers)
    assert resp.status_code == 422

    # Fora da faixa 2..36
    resp = client.post(url, json=_payload(u1.id, card.id, installments_count=1), headers=headers)
    assert resp.status_code == 422


def test_installments_with_fixed_split(db_session, ws_with_card, override_get_session):
    """Valor fixo pela despesa É parcelável: cada split é fatiado pelos N meses."""
    ws1, u1, u2, card = ws_with_card["ws1"], ws_with_card["u1"], ws_with_card["u2"], ws_with_card["card"]
    headers = ws_with_card["headers1"]

    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        json=_payload(u1.id, card.id, total_amount=100.0, installments_count=2, payers=[
            {"user_id": u1.id, "amount": 100.0},
        ], splits=[
            {"user_id": u1.id, "split_method": "fixed", "input_value": 60.0},
            {"user_id": u2.id, "split_method": "fixed", "input_value": 40.0},
        ]),
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    first = resp.json()

    siblings = db_session.exec(
        select(Transaction).where(
            Transaction.installment_group_id == first["installment_group_id"]
        ).order_by(Transaction.installment_no)
    ).all()
    assert len(siblings) == 2
    assert [tx.total_amount for tx in siblings] == [Decimal("50.00"), Decimal("50.00")]
    assert sum(tx.total_amount for tx in siblings) == Decimal("100.00")
    # 1ª parcela: 60→30 e 40→20
    splits = {s["user_id"]: s["computed_amount"] for s in first["splits"]}
    assert splits == {u1.id: "30.00", u2.id: "20.00"}


def test_installments_split_by_item_equal(db_session, ws_with_card, override_get_session):
    """Divisão POR ITEM parcelada: cada item é fatiado pelos N meses e os splits
    da parcela são derivados dos itens fatiados."""
    ws1, u1, u2, card = ws_with_card["ws1"], ws_with_card["u1"], ws_with_card["u2"], ws_with_card["card"]
    headers = ws_with_card["headers1"]

    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        json=_payload(
            u1.id, card.id, total_amount=90.0, installments_count=2,
            split_mode="item",
            payers=[{"user_id": u1.id, "amount": 90.0}],
            splits=[],
            items=[
                {"title": "Carne", "amount": 60.0, "shares": [
                    {"user_id": u1.id, "split_method": "equal", "input_value": 0},
                    {"user_id": u2.id, "split_method": "equal", "input_value": 0},
                ]},
                {"title": "Cerveja", "amount": 30.0, "shares": [
                    {"user_id": u1.id, "split_method": "equal", "input_value": 0},
                    {"user_id": u2.id, "split_method": "equal", "input_value": 0},
                ]},
            ],
        ),
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    first = resp.json()
    assert first["split_mode"] == "item"

    siblings = db_session.exec(
        select(Transaction).where(
            Transaction.installment_group_id == first["installment_group_id"]
        ).order_by(Transaction.installment_no)
    ).all()
    assert len(siblings) == 2
    # Carne 60→30/30, Cerveja 30→15/15 → cada parcela fecha 45
    assert [tx.total_amount for tx in siblings] == [Decimal("45.00"), Decimal("45.00")]
    assert sum(tx.total_amount for tx in siblings) == Decimal("90.00")

    # A 1ª parcela mantém os dois itens fatiados, cada um dividido igual
    items = {it["title"]: it for it in first["items"]}
    assert Decimal(items["Carne"]["amount"]) == Decimal("30.00")
    assert Decimal(items["Cerveja"]["amount"]) == Decimal("15.00")
    derived = {s["user_id"]: s["computed_amount"] for s in first["splits"]}
    assert derived == {u1.id: "22.50", u2.id: "22.50"}


def test_installments_split_by_item_fixed(db_session, ws_with_card, override_get_session):
    """Item com shares FIXAS parcelado: fatia o valor de cada share e deriva o
    total da linha da soma — shares seguem fechando o item em cada parcela."""
    ws1, u1, u2, card = ws_with_card["ws1"], ws_with_card["u1"], ws_with_card["u2"], ws_with_card["card"]
    headers = ws_with_card["headers1"]

    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        json=_payload(
            u1.id, card.id, total_amount=100.0, installments_count=2,
            split_mode="item",
            payers=[{"user_id": u1.id, "amount": 100.0}],
            splits=[],
            items=[
                {"title": "TV", "amount": 100.0, "shares": [
                    {"user_id": u1.id, "split_method": "fixed", "input_value": 70.0},
                    {"user_id": u2.id, "split_method": "fixed", "input_value": 30.0},
                ]},
            ],
        ),
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    first = resp.json()

    siblings = db_session.exec(
        select(Transaction).where(
            Transaction.installment_group_id == first["installment_group_id"]
        ).order_by(Transaction.installment_no)
    ).all()
    assert len(siblings) == 2
    assert [tx.total_amount for tx in siblings] == [Decimal("50.00"), Decimal("50.00")]
    assert sum(tx.total_amount for tx in siblings) == Decimal("100.00")

    # 70→35/35 e 30→15/15 → item de 50 por parcela, shares fechando
    tv = first["items"][0]
    assert Decimal(tv["amount"]) == Decimal("50.00")
    shares = {s["user_id"]: s["computed_amount"] for s in tv["shares"]}
    assert shares == {u1.id: "35.00", u2.id: "15.00"}
