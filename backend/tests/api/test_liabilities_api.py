"""Panorama de endividamento: financiamentos + faturas, total/mês/por pessoa."""
from datetime import datetime, UTC
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import app
from app.models.credit_card import CardStatement, CreditCard, StatementStatus
from app.models.transaction import Transaction, TransactionPayer, TransactionSplit, SplitMethod

client = TestClient(app)


def _create_financing(ws_id, headers):
    return client.post(
        f"/api/v1/workspaces/{ws_id}/financing",
        json={
            "title": "Carro",
            "total_amount": 1200.0,
            "interest_rate": 0.01,  # 1% a.m.
            "start_date": "2026-01-31",
            "installments_count": 12,
            "method": "SAC",
        },
        headers=headers,
    )


def _D(value) -> Decimal:
    return Decimal(str(value))


def test_overview_vazio(db_session: Session, setup_data, override_get_session):
    ws, headers = setup_data["ws1"], setup_data["headers1"]
    resp = client.get(f"/api/v1/workspaces/{ws.id}/liabilities/overview", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert _D(data["totals"]["grand_total"]) == Decimal("0")
    assert data["by_person"] == []
    assert data["financings"] == []
    assert data["cards"] == []


def test_overview_financiamento(db_session: Session, setup_data, override_get_session):
    ws, headers, u1 = setup_data["ws1"], setup_data["headers1"], setup_data["u1"]
    assert _create_financing(ws.id, headers).status_code == 200

    # Sem pagar nenhuma parcela: saldo devedor = principal inteiro (SAC 12×100).
    resp = client.get(f"/api/v1/workspaces/{ws.id}/liabilities/overview", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert _D(data["totals"]["financing_outstanding"]) == Decimal("1200.00")
    assert _D(data["totals"]["grand_total"]) == Decimal("1200.00")
    # Vai inteiro para o dono do financiamento
    assert len(data["by_person"]) == 1
    assert data["by_person"][0]["user_id"] == u1.id
    assert _D(data["by_person"][0]["financing"]) == Decimal("1200.00")
    assert _D(data["by_person"][0]["cards"]) == Decimal("0")

    # 1ª parcela vence em fev (mês de calendário a partir de 31/jan): 100 + 1% de 1200 = 112
    feb = client.get(
        f"/api/v1/workspaces/{ws.id}/liabilities/overview?month=2026-02", headers=headers
    ).json()
    assert _D(feb["month_due"]["financing_due"]) == Decimal("112.00")
    assert _D(feb["month_due"]["total"]) == Decimal("112.00")
    # Mês sem parcela → nada vence, mas o saldo total continua
    jul = client.get(
        f"/api/v1/workspaces/{ws.id}/liabilities/overview?month=2030-07", headers=headers
    ).json()
    assert _D(jul["month_due"]["total"]) == Decimal("0")
    assert _D(jul["totals"]["grand_total"]) == Decimal("1200.00")


def test_overview_cartao_rateado_por_splits(db_session: Session, setup_data, override_get_session):
    ws, u1, u2 = setup_data["ws1"], setup_data["u1"], setup_data["u2"]
    headers = setup_data["headers1"]

    card = CreditCard(name="Nubank", limit=Decimal("5000.00"), closing_day=10, due_day=20, workspace_id=ws.id)
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)

    stmt = CardStatement(
        card_id=card.id,
        month="2026-03",
        closing_date=datetime(2026, 3, 10, tzinfo=UTC),
        due_date=datetime(2026, 3, 20, tzinfo=UTC),
        status=StatementStatus.open,
    )
    db_session.add(stmt)
    db_session.commit()
    db_session.refresh(stmt)

    tx = Transaction(
        title="Compra cartão", total_amount=Decimal("200.00"),
        transaction_date=datetime(2026, 3, 5, tzinfo=UTC), billing_month="2026-03",
        workspace_id=ws.id, created_by_user_id=u1.id, currency="BRL",
        status="confirmed", statement_id=stmt.id,
    )
    db_session.add(tx)
    db_session.commit()
    db_session.refresh(tx)
    db_session.add(TransactionPayer(transaction_id=tx.id, user_id=u1.id, amount=Decimal("200.00")))
    db_session.add(TransactionSplit(transaction_id=tx.id, user_id=u1.id, split_method=SplitMethod.fixed, input_value=Decimal("120"), computed_amount=Decimal("120.00")))
    db_session.add(TransactionSplit(transaction_id=tx.id, user_id=u2.id, split_method=SplitMethod.fixed, input_value=Decimal("80"), computed_amount=Decimal("80.00")))
    db_session.commit()

    data = client.get(f"/api/v1/workspaces/{ws.id}/liabilities/overview?month=2026-03", headers=headers).json()
    assert _D(data["totals"]["cards_committed"]) == Decimal("200.00")
    assert _D(data["month_due"]["cards_due"]) == Decimal("200.00")

    by_person = {p["user_id"]: p for p in data["by_person"]}
    assert _D(by_person[u1.id]["cards"]) == Decimal("120.00")
    assert _D(by_person[u2.id]["cards"]) == Decimal("80.00")

    # Fatura paga libera o limite e sai do panorama
    stmt.status = StatementStatus.paid
    db_session.add(stmt)
    db_session.commit()
    paid = client.get(f"/api/v1/workspaces/{ws.id}/liabilities/overview?month=2026-03", headers=headers).json()
    assert _D(paid["totals"]["cards_committed"]) == Decimal("0")
    assert paid["by_person"] == []


def test_overview_mes_invalido(db_session: Session, setup_data, override_get_session):
    ws, headers = setup_data["ws1"], setup_data["headers1"]
    resp = client.get(f"/api/v1/workspaces/{ws.id}/liabilities/overview?month=xx", headers=headers)
    assert resp.status_code == 400
