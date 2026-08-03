"""Fatura com SALDO PENDENTE cumulativo.

O defeito que estes testes fecham: `pay_statement` aceitava qualquer valor
positivo e marcava a fatura como paga do mesmo jeito. Pagar R$ 1 de uma fatura de
R$ 1.000 devolvia `status = paid`, liberava o limite inteiro do cartão e ainda
travava o pagamento do resto — a fatura já não estava `closed`.

Agora o saldo é cumulativo (a fatura fica `closed` até chegar a zero) e o
sobrepagamento é recusado, pela mesma razão do ADR 0009 nos acertos: aceitar mais
do que se deve inventa crédito.
"""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.models.credit_card import CardStatement, CreditCard, StatementPayment, StatementStatus
from app.models.payment_account import PaymentAccount
from app.models.transaction import Transaction

client = TestClient(app)


@pytest.fixture(name="card_ws")
def card_ws_fixture(db_session: Session, setup_data):
    card = CreditCard(
        name="Nubank",
        limit=Decimal("5000.00"),
        closing_day=25,
        due_day=5,
        owner_user_id=setup_data["u1"].id,
    )
    account = PaymentAccount(name="Conta Corrente", owner_user_id=setup_data["u1"].id)
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


def _fatura_fechada(db_session, card_ws, valor: float) -> CardStatement:
    """Cria uma compra e devolve a fatura dela já fechada."""
    ws, u1, card = card_ws["ws1"], card_ws["u1"], card_ws["card"]
    headers = card_ws["headers1"]
    resp = _post_tx(ws.id, headers, u1.id, card.id, valor, "2026-01-10T12:00:00")
    assert resp.status_code == 200, resp.text
    tx = db_session.get(Transaction, resp.json()["id"])
    stmt = db_session.get(CardStatement, tx.statement_id)
    resp = client.post(
        f"/api/v1/me/credit-cards/{card.id}/statements/{stmt.id}/close", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return stmt


def test_pagamento_parcial_mantem_fatura_fechada_com_saldo(
    db_session, card_ws, override_get_session
):
    card, headers = card_ws["card"], card_ws["headers1"]
    stmt = _fatura_fechada(db_session, card_ws, 1000.0)
    base = f"/api/v1/me/credit-cards/{card.id}/statements/{stmt.id}"

    resp = client.post(f"{base}/pay", json={"amount": 1.0}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # ERA aqui que o defeito aparecia: R$ 1 devolvia "paid".
    assert body["status"] == "closed"
    assert Decimal(body["paid_amount"]) == Decimal("1.00")
    assert Decimal(body["remaining_amount"]) == Decimal("999.00")


def test_limite_liberado_e_proporcional_ao_que_foi_pago(
    db_session, card_ws, override_get_session
):
    card, headers = card_ws["card"], card_ws["headers1"]
    stmt = _fatura_fechada(db_session, card_ws, 1000.0)
    base = f"/api/v1/me/credit-cards/{card.id}/statements/{stmt.id}"

    client.post(f"{base}/pay", json={"amount": 400.0}, headers=headers)

    resp = client.get("/api/v1/me/credit-cards/", headers=headers)
    assert resp.status_code == 200, resp.text
    cartao = next(c for c in resp.json() if c["id"] == card.id)
    # Comprometido = SALDO (600), não o total da fatura (1000).
    assert Decimal(cartao["committed_amount"]) == Decimal("600.00")
    assert Decimal(cartao["available_limit"]) == Decimal("4400.00")


def test_pagamentos_sucessivos_quitam_a_fatura(db_session, card_ws, override_get_session):
    card, headers = card_ws["card"], card_ws["headers1"]
    stmt = _fatura_fechada(db_session, card_ws, 1000.0)
    base = f"/api/v1/me/credit-cards/{card.id}/statements/{stmt.id}"

    client.post(f"{base}/pay", json={"amount": 300.0}, headers=headers)
    # Antes o segundo pagamento era impossível: a fatura já estava paga.
    resp = client.post(f"{base}/pay", json={"amount": 700.0}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "paid"
    assert Decimal(body["paid_amount"]) == Decimal("1000.00")
    assert Decimal(body["remaining_amount"]) == Decimal("0.00")
    assert len(body["payments"]) == 2


def test_sobrepagamento_recusado_citando_o_saldo(db_session, card_ws, override_get_session):
    card, headers = card_ws["card"], card_ws["headers1"]
    stmt = _fatura_fechada(db_session, card_ws, 1000.0)
    base = f"/api/v1/me/credit-cards/{card.id}/statements/{stmt.id}"

    client.post(f"{base}/pay", json={"amount": 300.0}, headers=headers)
    resp = client.post(f"{base}/pay", json={"amount": 900.0}, headers=headers)
    assert resp.status_code == 409, resp.text
    # A mensagem cita o SALDO (700), não o total — é o número que o usuário vê
    # na mesma tela.
    assert "700" in resp.json()["error"]["message"]


def test_sem_valor_paga_o_saldo_restante(db_session, card_ws, override_get_session):
    card, headers = card_ws["card"], card_ws["headers1"]
    stmt = _fatura_fechada(db_session, card_ws, 1000.0)
    base = f"/api/v1/me/credit-cards/{card.id}/statements/{stmt.id}"

    client.post(f"{base}/pay", json={"amount": 250.0}, headers=headers)
    # Omitir `amount` quitava o TOTAL congelado; agora quita o que falta.
    resp = client.post(f"{base}/pay", json={}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "paid"
    assert Decimal(body["payments"][-1]["amount"]) == Decimal("750.00")


def test_reabrir_fechada_estorna_o_pagamento_parcial(
    db_session, card_ws, override_get_session
):
    card, headers = card_ws["card"], card_ws["headers1"]
    stmt = _fatura_fechada(db_session, card_ws, 1000.0)
    base = f"/api/v1/me/credit-cards/{card.id}/statements/{stmt.id}"

    client.post(f"{base}/pay", json={"amount": 400.0}, headers=headers)
    # `closed → open` também estorna: uma fatura aberta volta a somar em tempo
    # real, e não haveria saldo a que o pagamento se referisse.
    resp = client.post(f"{base}/reopen", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "open"

    db_session.expire_all()
    vivos = db_session.exec(
        select(StatementPayment).where(
            StatementPayment.statement_id == stmt.id,
            StatementPayment.deleted_at.is_(None),
        )
    ).all()
    assert vivos == []


def test_fatura_quitada_nao_aceita_novo_pagamento(db_session, card_ws, override_get_session):
    card, headers = card_ws["card"], card_ws["headers1"]
    stmt = _fatura_fechada(db_session, card_ws, 100.0)
    base = f"/api/v1/me/credit-cards/{card.id}/statements/{stmt.id}"

    client.post(f"{base}/pay", json={"amount": 100.0}, headers=headers)
    resp = client.post(f"{base}/pay", json={"amount": 10.0}, headers=headers)
    assert resp.status_code == 409

    db_session.expire_all()
    assert db_session.get(CardStatement, stmt.id).status == StatementStatus.paid
