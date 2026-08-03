"""`next_due` na listagem de cartões: a fatura que pede atenção.

A tela de cartões precisa avisar "fechada", "vence em N dias" ou "vencida" para
CADA cartão. Sem este campo ela teria que buscar as faturas de cada cartão só
para descobrir se existe algo a pagar.
"""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.domain.dates import today_local
from app.main import app
from app.models.credit_card import CreditCard, CardStatement, StatementStatus
from app.services.credit_card_service import CreditCardService

client = TestClient(app)


@pytest.fixture(name="card_ws")
def card_ws_fixture(db_session: Session, setup_data):
    card = CreditCard(
        name="Nubank",
        limit=Decimal("5000.00"), closing_day=25, due_day=5, owner_user_id=setup_data["u1"].id)
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    setup_data["card"] = card
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


def _cards(ws_id, headers):
    resp = client.get("/api/v1/me/credit-cards/", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_cartao_sem_fatura_nao_tem_next_due(card_ws, override_get_session):
    ws, headers = card_ws["ws1"], card_ws["headers1"]
    assert _cards(ws.id, headers)[0]["next_due"] is None


def test_next_due_aponta_a_fatura_aberta_com_valor(card_ws, override_get_session, db_session):
    ws, u1, card = card_ws["ws1"], card_ws["u1"], card_ws["card"]
    headers = card_ws["headers1"]

    resp = _post_tx(ws.id, headers, u1.id, card.id, 250.0, "2026-01-10T12:00:00")
    assert resp.status_code == 200, resp.text

    next_due = _cards(ws.id, headers)[0]["next_due"]
    assert next_due is not None
    assert next_due["month"] == "2026-01"
    assert next_due["status"] == "open"
    assert Decimal(next_due["amount"]) == Decimal("250.00")
    # dia 5 > dia 25 é falso → vencimento rola para o mês seguinte
    assert next_due["due_date"].startswith("2026-02-05")
    assert next_due["closing_date"].startswith("2026-01-25")


def test_next_due_e_a_fatura_NAO_PAGA_MAIS_ANTIGA(card_ws, override_get_session, db_session):
    """Com duas faturas em aberto, quem corre risco é a de vencimento mais
    próximo — a mais antiga."""
    ws, u1, card = card_ws["ws1"], card_ws["u1"], card_ws["card"]
    headers = card_ws["headers1"]

    _post_tx(ws.id, headers, u1.id, card.id, 100.0, "2026-01-10T12:00:00")
    _post_tx(ws.id, headers, u1.id, card.id, 400.0, "2026-02-10T12:00:00")

    next_due = _cards(ws.id, headers)[0]["next_due"]
    assert next_due["month"] == "2026-01"
    assert Decimal(next_due["amount"]) == Decimal("100.00")


def test_fatura_paga_sai_do_next_due(card_ws, override_get_session, db_session):
    ws, u1, card = card_ws["ws1"], card_ws["u1"], card_ws["card"]
    headers = card_ws["headers1"]

    _post_tx(ws.id, headers, u1.id, card.id, 100.0, "2026-01-10T12:00:00")
    _post_tx(ws.id, headers, u1.id, card.id, 400.0, "2026-02-10T12:00:00")
    jan = _cards(ws.id, headers)[0]["next_due"]["statement_id"]

    base = f"/api/v1/me/credit-cards/{card.id}/statements/{jan}"
    assert client.post(f"{base}/close", headers=headers).status_code == 200
    assert client.post(f"{base}/pay", json={}, headers=headers).status_code == 200

    next_due = _cards(ws.id, headers)[0]["next_due"]
    assert next_due["month"] == "2026-02"
    assert Decimal(next_due["amount"]) == Decimal("400.00")


def test_fatura_zerada_nao_vira_alerta(card_ws, override_get_session, db_session):
    """A fatura do ciclo corrente é materializada mesmo sem compras — avisar
    sobre uma fatura de R$ 0,00 seria ruído."""
    ws, card, headers = card_ws["ws1"], card_ws["card"], card_ws["headers1"]
    resp = client.get(
        f"/api/v1/me/credit-cards/{card.id}/statements", headers=headers
    )
    assert resp.status_code == 200
    assert len(resp.json()) >= 1  # materializada
    assert _cards(ws.id, headers)[0]["next_due"] is None


def test_is_overdue_marca_vencida_e_ignora_paga(db_session, card_ws):
    """`is_overdue` é derivado da data — não depende de job carimbando status."""
    card = card_ws["card"]
    # Ancorado no dia de calendário LOCAL, que é a referência de `is_overdue`.
    # Com `datetime.now(UTC)` o teste falhava das 21h à meia-noite em São Paulo:
    # o "ontem" do UTC ainda é HOJE no calendário do usuário.
    hoje = today_local()
    ontem = datetime.combine(hoje - timedelta(days=1), datetime.min.time())
    amanha = datetime.combine(hoje + timedelta(days=1), datetime.min.time())

    vencida = CardStatement(
        card_id=card.id, month="2020-01", closing_date=ontem, due_date=ontem,
        status=StatementStatus.closed,
    )
    a_vencer = CardStatement(
        card_id=card.id, month="2020-02", closing_date=ontem, due_date=amanha,
        status=StatementStatus.closed,
    )
    paga_atrasada = CardStatement(
        card_id=card.id, month="2020-03", closing_date=ontem, due_date=ontem,
        status=StatementStatus.paid,
    )

    assert CreditCardService.is_overdue(vencida) is True
    assert CreditCardService.is_overdue(a_vencer) is False
    assert CreditCardService.is_overdue(paga_atrasada) is False


def test_committed_continua_somando_todas_as_nao_pagas(card_ws, override_get_session):
    """`card_committed` passou a delegar em `card_overview` — o comprometido
    segue sendo a soma de TODAS as não pagas, não só a do alerta."""
    ws, u1, card = card_ws["ws1"], card_ws["u1"], card_ws["card"]
    headers = card_ws["headers1"]

    _post_tx(ws.id, headers, u1.id, card.id, 100.0, "2026-01-10T12:00:00")
    _post_tx(ws.id, headers, u1.id, card.id, 400.0, "2026-02-10T12:00:00")

    card_json = _cards(ws.id, headers)[0]
    assert Decimal(card_json["committed_amount"]) == Decimal("500.00")
    assert Decimal(card_json["available_limit"]) == Decimal("4500.00")


def test_mudar_dia_do_ciclo_atualiza_a_fatura_aberta(db_session, setup_data, override_get_session):
    """Corrigir closing_day/due_day tem que valer para a fatura EM ABERTO.

    As datas da fatura eram congeladas na criação dela: mudar o vencimento no
    cadastro do cartão não mexia em nada, e o aviso da fatura seguia anunciando
    a data antiga — num app de finanças, vencimento errado é fatura paga com
    atraso. Fechadas/pagas continuam congeladas (são histórico do cobrado).
    """
    from app.models.credit_card import CardStatement, StatementStatus
    from sqlmodel import select

    _ws, headers = setup_data["ws1"], setup_data["headers1"]

    resp = client.post(
        "/api/v1/me/credit-cards/",
        json={"name": "Cartão", "limit": 5000, "closing_day": 5, "due_day": 15},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    card_id = resp.json()["id"]

    # Materializa a fatura do ciclo corrente
    resp = client.get(f"/api/v1/me/credit-cards/{card_id}/statements", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json(), "nenhuma fatura materializada"

    resp = client.put(
        f"/api/v1/me/credit-cards/{card_id}",
        json={"closing_day": 20, "due_day": 28},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    abertas = db_session.exec(
        select(CardStatement)
        .where(CardStatement.card_id == card_id)
        .where(CardStatement.status == StatementStatus.open)
    ).all()
    assert abertas, "o cartão ficou sem fatura aberta"
    for stmt in abertas:
        assert stmt.closing_date.day == 20, "fechamento não acompanhou o novo dia do ciclo"
        assert stmt.due_date.day == 28, "vencimento não acompanhou o novo dia do ciclo"
