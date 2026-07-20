"""Ciclo da fatura open→closed→paid + reabertura, pagamento por conta e limite
comprometido/disponível (ADR 0011)."""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.models.credit_card import CreditCard, CardStatement, StatementPayment, StatementStatus
from app.models.payment_account import PaymentAccount
from app.models.transaction import Transaction

client = TestClient(app)


@pytest.fixture(name="card_ws")
def card_ws_fixture(db_session: Session, setup_data):
    card = CreditCard(
        workspace_id=setup_data["ws1"].id, name="Nubank",
        limit=Decimal("5000.00"), closing_day=25, due_day=5,
    )
    account = PaymentAccount(workspace_id=setup_data["ws1"].id, name="Conta Corrente")
    db_session.add_all([card, account])
    db_session.commit()
    db_session.refresh(card)
    db_session.refresh(account)
    setup_data["card"] = card
    setup_data["account"] = account
    return setup_data


def _post_tx(ws_id, headers, user_id, card_id, amount, dt):
    return client.post(
        f"/api/v1/workspaces/{ws_id}/transactions/",
        json={
            "title": "Compra",
            "total_amount": amount,
            "transaction_date": dt,
            "credit_card_id": card_id,
            "payment_method": "credit_card",
            "payers": [{"user_id": user_id, "amount": amount}],
            "splits": [{"user_id": user_id, "split_method": "equal", "input_value": 0}],
        },
        headers=headers,
    )


def _statement_of(db_session, tx_id):
    tx = db_session.get(Transaction, tx_id)
    return db_session.get(CardStatement, tx.statement_id)


def test_ciclo_fechar_pagar_reabrir(db_session, card_ws, override_get_session):
    ws, u1, card, account = card_ws["ws1"], card_ws["u1"], card_ws["card"], card_ws["account"]
    headers = card_ws["headers1"]

    resp = _post_tx(ws.id, headers, u1.id, card.id, 100.0, "2026-01-10T12:00:00")
    assert resp.status_code == 200, resp.text
    stmt = _statement_of(db_session, resp.json()["id"])
    assert stmt.status == StatementStatus.open

    base = f"/api/v1/workspaces/{ws.id}/credit-cards/{card.id}/statements/{stmt.id}"

    # Fechar: congela o total e carimba closed_at
    resp = client.post(f"{base}/close", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "closed"
    assert body["closed_at"] is not None
    assert Decimal(str(body["computed_total"])) == Decimal("100.00")

    # Pagar exige conta válida → status paid + StatementPayment
    resp = client.post(f"{base}/pay", json={"account_id": account.id}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "paid"
    db_session.expire_all()
    payments = db_session.exec(
        select(StatementPayment).where(
            StatementPayment.statement_id == stmt.id,
            StatementPayment.deleted_at.is_(None),
        )
    ).all()
    assert len(payments) == 1
    assert payments[0].account_id == account.id
    assert payments[0].amount == Decimal("100.00")

    # Reabrir uma paga estorna o pagamento → volta para closed
    resp = client.post(f"{base}/reopen", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "closed"
    db_session.expire_all()
    active = db_session.exec(
        select(StatementPayment).where(
            StatementPayment.statement_id == stmt.id,
            StatementPayment.deleted_at.is_(None),
        )
    ).all()
    assert len(active) == 0

    # Reabrir de novo volta para open
    resp = client.post(f"{base}/reopen", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "open"


def test_pagar_sem_fechar_e_conflito(db_session, card_ws, override_get_session):
    ws, u1, card, account = card_ws["ws1"], card_ws["u1"], card_ws["card"], card_ws["account"]
    headers = card_ws["headers1"]
    resp = _post_tx(ws.id, headers, u1.id, card.id, 100.0, "2026-01-10T12:00:00")
    stmt = _statement_of(db_session, resp.json()["id"])
    base = f"/api/v1/workspaces/{ws.id}/credit-cards/{card.id}/statements/{stmt.id}"

    resp = client.post(f"{base}/pay", json={"account_id": account.id}, headers=headers)
    assert resp.status_code == 409  # aberta não pode ser paga direto


def test_pagar_com_conta_de_outro_workspace(db_session, card_ws, override_get_session):
    ws, u1, card = card_ws["ws1"], card_ws["u1"], card_ws["card"]
    headers = card_ws["headers1"]
    foreign_account = PaymentAccount(workspace_id=card_ws["ws2"].id, name="Alheia")
    db_session.add(foreign_account)
    db_session.commit()
    db_session.refresh(foreign_account)

    resp = _post_tx(ws.id, headers, u1.id, card.id, 100.0, "2026-01-10T12:00:00")
    stmt = _statement_of(db_session, resp.json()["id"])
    base = f"/api/v1/workspaces/{ws.id}/credit-cards/{card.id}/statements/{stmt.id}"
    client.post(f"{base}/close", headers=headers)

    resp = client.post(f"{base}/pay", json={"account_id": foreign_account.id}, headers=headers)
    assert resp.status_code == 400


def test_limite_comprometido_e_disponivel(db_session, card_ws, override_get_session):
    ws, u1, card = card_ws["ws1"], card_ws["u1"], card_ws["card"]
    account = card_ws["account"]
    headers = card_ws["headers1"]

    _post_tx(ws.id, headers, u1.id, card.id, 200.0, "2026-01-10T12:00:00")
    resp = _post_tx(ws.id, headers, u1.id, card.id, 300.0, "2026-01-11T12:00:00")
    stmt = _statement_of(db_session, resp.json()["id"])

    cards = client.get(f"/api/v1/workspaces/{ws.id}/credit-cards/", headers=headers).json()
    assert Decimal(str(cards[0]["committed_amount"])) == Decimal("500.00")
    assert Decimal(str(cards[0]["available_limit"])) == Decimal("4500.00")

    # Fatura paga libera o limite
    base = f"/api/v1/workspaces/{ws.id}/credit-cards/{card.id}/statements/{stmt.id}"
    client.post(f"{base}/close", headers=headers)
    client.post(f"{base}/pay", json={"account_id": account.id}, headers=headers)

    cards = client.get(f"/api/v1/workspaces/{ws.id}/credit-cards/", headers=headers).json()
    assert Decimal(str(cards[0]["committed_amount"])) == Decimal("0.00")
    assert Decimal(str(cards[0]["available_limit"])) == Decimal("5000.00")


def test_fatura_fechada_nao_recebe_novas_compras(db_session, card_ws, override_get_session):
    """Compra que chegaria numa fatura já fechada rola para a próxima aberta."""
    ws, u1, card = card_ws["ws1"], card_ws["u1"], card_ws["card"]
    headers = card_ws["headers1"]

    resp = _post_tx(ws.id, headers, u1.id, card.id, 100.0, "2026-01-10T12:00:00")
    stmt1 = _statement_of(db_session, resp.json()["id"])
    assert stmt1.month == "2026-01"

    base = f"/api/v1/workspaces/{ws.id}/credit-cards/{card.id}/statements/{stmt1.id}"
    client.post(f"{base}/close", headers=headers)

    resp = _post_tx(ws.id, headers, u1.id, card.id, 50.0, "2026-01-11T12:00:00")
    db_session.expire_all()
    stmt2 = _statement_of(db_session, resp.json()["id"])
    assert stmt2.id != stmt1.id
    assert stmt2.month == "2026-02"
    # A fatura fechada continua com o total congelado, intocada
    db_session.refresh(stmt1)
    assert stmt1.total_amount == Decimal("100.00")


def test_total_congelado_ignora_edicao_posterior(db_session, card_ws, override_get_session):
    ws, u1, card = card_ws["ws1"], card_ws["u1"], card_ws["card"]
    headers = card_ws["headers1"]
    resp = _post_tx(ws.id, headers, u1.id, card.id, 100.0, "2026-01-10T12:00:00")
    tx_id = resp.json()["id"]
    stmt = _statement_of(db_session, tx_id)
    base = f"/api/v1/workspaces/{ws.id}/credit-cards/{card.id}/statements/{stmt.id}"
    client.post(f"{base}/close", headers=headers)

    # Cancelar a transação depois do fechamento NÃO altera o total faturado
    client.put(
        f"/api/v1/workspaces/{ws.id}/transactions/{tx_id}",
        json={"status": "cancelled"},
        headers=headers,
    )
    detail = client.get(f"{base.rsplit('/', 1)[0]}/{stmt.id}", headers=headers).json()
    assert Decimal(str(detail["computed_total"])) == Decimal("100.00")


def test_overdue_derivado(db_session, card_ws, override_get_session):
    ws, u1, card = card_ws["ws1"], card_ws["u1"], card_ws["card"]
    account = card_ws["account"]
    headers = card_ws["headers1"]
    # Vencimento 2026-02-05 já passou (hoje é depois) → overdue enquanto não paga
    resp = _post_tx(ws.id, headers, u1.id, card.id, 100.0, "2026-01-10T12:00:00")
    stmt = _statement_of(db_session, resp.json()["id"])
    base = f"/api/v1/workspaces/{ws.id}/credit-cards/{card.id}/statements/{stmt.id}"

    detail = client.get(f"{base.rsplit('/', 1)[0]}/{stmt.id}", headers=headers).json()
    assert detail["is_overdue"] is True

    client.post(f"{base}/close", headers=headers)
    resp = client.post(f"{base}/pay", json={"account_id": account.id}, headers=headers)
    assert resp.json()["is_overdue"] is False
