"""Fatura derivada exclusivamente no servidor (ADR 0002).

- statement_id do cliente é ignorado (IDOR bloqueado por construção);
- mudar data ou cartão rerroteia a fatura;
- remover o cartão limpa o vínculo;
- cartão de outro workspace é rejeitado no update.
"""
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.models.credit_card import CreditCard, CardStatement, StatementStatus
from app.models.transaction import Transaction

client = TestClient(app)


@pytest.fixture(name="two_ws_cards")
def two_ws_cards_fixture(db_session: Session, setup_data):
    """Um cartão em cada workspace + uma fatura pré-existente no ws2."""
    card1 = CreditCard(
        workspace_id=setup_data["ws1"].id, name="Card WS1",
        limit=Decimal("5000.00"), closing_day=25, due_day=5,
    )
    card2 = CreditCard(
        workspace_id=setup_data["ws2"].id, name="Card WS2",
        limit=Decimal("5000.00"), closing_day=25, due_day=5,
    )
    db_session.add_all([card1, card2])
    db_session.flush()
    foreign_stmt = CardStatement(
        card_id=card2.id, month="2026-03", status=StatementStatus.open,
        closing_date=datetime(2026, 3, 25), due_date=datetime(2026, 4, 5),
    )
    db_session.add(foreign_stmt)
    db_session.commit()
    for obj in (card1, card2, foreign_stmt):
        db_session.refresh(obj)
    setup_data["card1"] = card1
    setup_data["foreign_stmt"] = foreign_stmt
    return setup_data


def _payload(user_id, **overrides):
    payload = {
        "title": "Compra",
        "total_amount": 50.0,
        "transaction_date": "2026-01-10T12:00:00",
        "payers": [{"user_id": user_id, "amount": 50.0}],
        "splits": [{"user_id": user_id, "split_method": "equal", "input_value": 0}],
    }
    payload.update(overrides)
    return payload


def test_statement_id_do_cliente_e_ignorado(db_session, two_ws_cards, override_get_session):
    """IDOR: apontar para fatura de outro workspace não pode ter efeito."""
    ws1, u1 = two_ws_cards["ws1"], two_ws_cards["u1"]
    foreign = two_ws_cards["foreign_stmt"]

    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        json=_payload(u1.id, statement_id=foreign.id),
        headers=two_ws_cards["headers1"],
    )
    assert resp.status_code == 200, resp.text
    tx = db_session.get(Transaction, resp.json()["id"])
    assert tx.statement_id is None  # sem cartão, sem fatura — campo do payload ignorado


def test_com_cartao_fatura_e_derivada_mesmo_com_statement_id_forjado(
    db_session, two_ws_cards, override_get_session
):
    ws1, u1, card1 = two_ws_cards["ws1"], two_ws_cards["u1"], two_ws_cards["card1"]
    foreign = two_ws_cards["foreign_stmt"]

    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        json=_payload(
            u1.id,
            credit_card_id=card1.id,
            payment_method="credit_card",
            statement_id=foreign.id,
        ),
        headers=two_ws_cards["headers1"],
    )
    assert resp.status_code == 200, resp.text
    tx = db_session.get(Transaction, resp.json()["id"])
    assert tx.statement_id is not None
    assert tx.statement_id != foreign.id
    stmt = db_session.get(CardStatement, tx.statement_id)
    assert stmt.card_id == card1.id
    assert stmt.month == "2026-01"  # dia 10 < fechamento 25 → mês corrente


def test_mudar_data_rerroteia_fatura(db_session, two_ws_cards, override_get_session):
    ws1, u1, card1 = two_ws_cards["ws1"], two_ws_cards["u1"], two_ws_cards["card1"]
    headers = two_ws_cards["headers1"]

    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        json=_payload(u1.id, credit_card_id=card1.id, payment_method="credit_card"),
        headers=headers,
    )
    tx_id = resp.json()["id"]
    original_stmt = db_session.get(Transaction, tx_id).statement_id

    # Dia 26 >= fechamento 25 → fatura do mês seguinte (2026-03)
    resp = client.put(
        f"/api/v1/workspaces/{ws1.id}/transactions/{tx_id}",
        json={"transaction_date": "2026-02-26T12:00:00"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    tx = db_session.get(Transaction, tx_id)
    assert tx.statement_id != original_stmt
    assert db_session.get(CardStatement, tx.statement_id).month == "2026-03"
    assert tx.billing_month == "2026-02"  # billing_month recalculado pela data


def test_remover_cartao_limpa_fatura(db_session, two_ws_cards, override_get_session):
    ws1, u1, card1 = two_ws_cards["ws1"], two_ws_cards["u1"], two_ws_cards["card1"]
    headers = two_ws_cards["headers1"]

    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        json=_payload(u1.id, credit_card_id=card1.id, payment_method="credit_card"),
        headers=headers,
    )
    tx_id = resp.json()["id"]

    resp = client.put(
        f"/api/v1/workspaces/{ws1.id}/transactions/{tx_id}",
        json={"credit_card_id": None, "payment_method": "pix"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    tx = db_session.get(Transaction, tx_id)
    assert tx.statement_id is None
    assert tx.credit_card_id is None


def test_update_com_cartao_de_outro_workspace_e_rejeitado(
    db_session, two_ws_cards, override_get_session
):
    ws1, u1 = two_ws_cards["ws1"], two_ws_cards["u1"]
    card2_id = two_ws_cards["foreign_stmt"].card_id
    headers = two_ws_cards["headers1"]

    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        json=_payload(u1.id),
        headers=headers,
    )
    tx_id = resp.json()["id"]

    resp = client.put(
        f"/api/v1/workspaces/{ws1.id}/transactions/{tx_id}",
        json={"credit_card_id": card2_id, "payment_method": "credit_card"},
        headers=headers,
    )
    assert resp.status_code == 400
    db_session.expire_all()
    assert db_session.get(Transaction, tx_id).credit_card_id is None


def test_statement_for_anuncia_a_fatura_sem_criar_nada(
    db_session, two_ws_cards, override_get_session
):
    """A UI precisa ANUNCIAR o destino, e perguntar não pode criar fatura.

    A regra tem duas partes que o formulário não contava — a partir do dia de
    fechamento a compra vai para o mês seguinte, e se aquela fatura já estiver
    fechada ela rola para frente. O usuário só descobria depois de salvar.
    Consultar enquanto digita não pode deixar faturas vazias para trás.
    """
    ws1, headers = two_ws_cards["ws1"], two_ws_cards["headers1"]
    card1 = db_session.exec(
        select(CreditCard).where(CreditCard.workspace_id == ws1.id)
    ).first()  # closing_day=25, due_day=5

    def alvo(dia_iso: str) -> dict:
        resp = client.get(
            f"/api/v1/workspaces/{ws1.id}/credit-cards/{card1.id}/statement-for",
            params={"on": dia_iso},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    # Antes do fechamento (dia 25): fatura do próprio mês, vencendo em 05/04
    antes = alvo("2026-03-10")
    assert antes["month"] == "2026-03"
    assert antes["due_date"].startswith("2026-04-05")
    assert antes["exists"] is False        # ainda não existe
    assert antes["rolled_forward"] is False

    # A partir do fechamento: cai na fatura do mês SEGUINTE
    depois = alvo("2026-03-25")
    assert depois["month"] == "2026-04"
    assert depois["rolled_forward"] is False  # é a regra do ciclo, não rolagem

    # Consultar não pode ter criado fatura nenhuma
    assert db_session.exec(
        select(CardStatement).where(CardStatement.card_id == card1.id)
    ).all() == []

    # Fatura de março FECHADA: a compra do dia 10 rola para abril
    fechada = CardStatement(
        card_id=card1.id, month="2026-03", status=StatementStatus.closed,
        closing_date=datetime(2026, 3, 25), due_date=datetime(2026, 4, 5),
        total_amount=Decimal("100.00"),
    )
    db_session.add(fechada)
    db_session.commit()

    rolada = alvo("2026-03-10")
    assert rolada["month"] == "2026-04"
    assert rolada["rolled_forward"] is True

    # E o anúncio bate com o que o POST realmente faz (mesma fonte de verdade)
    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        json={**_payload(two_ws_cards["u1"].id), "credit_card_id": card1.id,
              "payment_method": "credit_card", "transaction_date": "2026-03-10T12:00:00"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    stmt = db_session.get(CardStatement, resp.json()["statement_id"])
    assert stmt.month == rolada["month"]
