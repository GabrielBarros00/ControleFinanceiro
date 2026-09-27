"""A lista de faturas do cartão faz o mesmo número de consultas com 3 ou 12 abertas.

Auditoria 2026-09-26, P4. Pagamentos e contagem de excluídos já vinham em lote,
mas o total de cada fatura ABERTA era um SUM por fatura (`effective_total` dentro
do laço). O fechamento é manual, então faturas antigas podem ficar abertas
indefinidamente — e o custo crescia com a idade do cartão.
"""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.main import app
from app.models.credit_card import CardStatement, CreditCard, StatementStatus
from app.models.transaction import Transaction, TransactionStatus


@pytest.fixture(name="client")
def client_fixture(override_get_session):
    return TestClient(app)


def _cartao_com_faturas_abertas(db, ws, dono, abertas: int, nome: str) -> CreditCard:
    cartao = CreditCard(name=nome, limit=Decimal("5000.00"), closing_day=3, due_day=10,
                        owner_user_id=dono.id, currency="BRL")
    db.add(cartao)
    db.commit()
    for i in range(abertas):
        ano, mes = divmod(2024 * 12 + i, 12)
        fechamento = datetime(ano, mes + 1, 3, 12, tzinfo=UTC)
        f = CardStatement(card_id=cartao.id, month=f"{ano:04d}-{mes + 1:02d}", closing_date=fechamento,
                          due_date=fechamento + timedelta(days=7), status=StatementStatus.open,
                          total_amount=Decimal("0.00"))
        db.add(f)
        db.flush()
        valor = Decimal(f"{i + 1}0.00")
        db.add(Transaction(
            workspace_id=ws.id, created_by_user_id=dono.id, title="compra", total_amount=valor,
            currency="BRL", transaction_date=fechamento - timedelta(days=5),
            status=TransactionStatus.confirmed, credit_card_id=cartao.id, statement_id=f.id,
            statement_amount=valor, statement_currency="BRL",
        ))
    db.commit()
    return cartao


def _consultas(client, db, url, headers):
    db.expire_all()
    n = {"q": 0}

    def conta(*_a, **_k):
        n["q"] += 1

    event.listen(Engine, "before_cursor_execute", conta)
    try:
        res = client.get(url, headers=headers)
    finally:
        event.remove(Engine, "before_cursor_execute", conta)
    assert res.status_code == 200, res.text
    return n["q"], res.json()


def test_consultas_nao_crescem_com_as_faturas_abertas(client, db_session, setup_data):
    ws, u1, headers = setup_data["ws1"], setup_data["u1"], setup_data["headers1"]
    poucas = _cartao_com_faturas_abertas(db_session, ws, u1, 3, "Poucas")
    muitas = _cartao_com_faturas_abertas(db_session, ws, u1, 12, "Muitas")
    # Aquecimento: a primeira chamada materializa a fatura do ciclo corrente.
    for c in (poucas, muitas):
        _consultas(client, db_session, f"/api/v1/me/credit-cards/{c.id}/statements", headers)

    n3, corpo3 = _consultas(client, db_session, f"/api/v1/me/credit-cards/{poucas.id}/statements", headers)
    n12, corpo12 = _consultas(client, db_session, f"/api/v1/me/credit-cards/{muitas.id}/statements", headers)

    # O número continua o de cada fatura: R$ 10, 20, 30… na ordem dos meses.
    por_mes = {f["month"]: Decimal(str(f["computed_total"])) for f in corpo12}
    assert por_mes["2024-01"] == Decimal("10.00")
    assert por_mes["2024-12"] == Decimal("120.00")
    assert len([f for f in corpo12 if f["status"] == "open"]) >= 12

    assert n12 == n3, f"3 abertas: {n3} consultas; 12 abertas: {n12}"
