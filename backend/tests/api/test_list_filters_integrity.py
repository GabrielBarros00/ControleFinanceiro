"""Regressão dos filtros da listagem de lançamentos.

- Categoria duplicava a linha quando a despesa tinha 2 itens da MESMA categoria
  (join sem DISTINCT): a lista mostrava o lançamento duas vezes e `total` vinha 2.
- A busca passava '%' cru para o LIKE, então procurar "%" casava com tudo.
- `total_amount` é a soma do filtro inteiro (a tela mostra ao lado da contagem).
"""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.category import Category
from app.models.tag import Tag, TransactionTagLink
from app.models.transaction import Transaction, TransactionItem


@pytest.fixture(name="client")
def client_fixture(override_get_session):
    return TestClient(app)


def _tx(db, ws, user, title="Compra", amount="100.00", month="2026-07") -> Transaction:
    tx = Transaction(
        title=title,
        total_amount=Decimal(amount),
        billing_month=month,
        workspace_id=ws.id,
        created_by_user_id=user.id,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx


def test_filtro_de_categoria_nao_duplica_lancamento(client, db_session, setup_data):
    ws, u1 = setup_data["ws1"], setup_data["u1"]
    cat = Category(workspace_id=ws.id, name="Mercado")
    db_session.add(cat)
    db_session.commit()
    db_session.refresh(cat)

    tx = _tx(db_session, ws, u1)
    # Dois itens da MESMA categoria na mesma despesa
    db_session.add(TransactionItem(
        transaction_id=tx.id, title="Arroz", amount=Decimal("60.00"), category_id=cat.id
    ))
    db_session.add(TransactionItem(
        transaction_id=tx.id, title="Feijão", amount=Decimal("40.00"), category_id=cat.id
    ))
    db_session.commit()

    res = client.get(
        f"/api/v1/workspaces/{ws.id}/transactions/?category_id={cat.id}",
        headers=setup_data["headers1"],
    )
    body = res.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == tx.id
    # E a soma não conta o lançamento duas vezes
    assert Decimal(str(body["total_amount"])) == Decimal("100.00")


def test_filtro_de_tag_nao_duplica_lancamento(client, db_session, setup_data):
    ws, u1 = setup_data["ws1"], setup_data["u1"]
    tag = Tag(workspace_id=ws.id, name="viagem")
    db_session.add(tag)
    db_session.commit()
    db_session.refresh(tag)

    tx = _tx(db_session, ws, u1)
    db_session.add(TransactionTagLink(transaction_id=tx.id, tag_id=tag.id))
    db_session.commit()

    res = client.get(
        f"/api/v1/workspaces/{ws.id}/transactions/?tag_id={tag.id}",
        headers=setup_data["headers1"],
    )
    assert res.json()["total"] == 1


def test_busca_escapa_curinga_do_like(client, db_session, setup_data):
    ws, u1 = setup_data["ws1"], setup_data["u1"]
    _tx(db_session, ws, u1, title="Padaria")
    _tx(db_session, ws, u1, title="Farmácia")
    _tx(db_session, ws, u1, title="Desconto de 10% na loja")

    # '%' é curinga do LIKE: sem escape isto devolvia TODOS os lançamentos
    res = client.get(
        f"/api/v1/workspaces/{ws.id}/transactions/?search=%25", headers=setup_data["headers1"]
    )
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "Desconto de 10% na loja"

    # '_' idem (casaria com qualquer caractere)
    res = client.get(
        f"/api/v1/workspaces/{ws.id}/transactions/?search=_", headers=setup_data["headers1"]
    )
    assert res.json()["total"] == 0

    # busca normal segue funcionando
    res = client.get(
        f"/api/v1/workspaces/{ws.id}/transactions/?search=Pada", headers=setup_data["headers1"]
    )
    assert res.json()["total"] == 1


def test_total_amount_e_do_filtro_inteiro_nao_da_pagina(client, db_session, setup_data):
    ws, u1 = setup_data["ws1"], setup_data["u1"]
    for i in range(5):
        _tx(db_session, ws, u1, title=f"Gasto {i}", amount="10.00")

    res = client.get(
        f"/api/v1/workspaces/{ws.id}/transactions/?limit=2&page=1", headers=setup_data["headers1"]
    )
    body = res.json()
    assert len(body["items"]) == 2          # a página traz 2
    assert body["total"] == 5               # mas a contagem é global
    assert Decimal(str(body["total_amount"])) == Decimal("50.00")  # e a soma também


def test_titulo_gigante_e_recusado(client, db_session, setup_data):
    ws, u1 = setup_data["ws1"], setup_data["u1"]
    payload = {
        "title": "X" * 5000,
        "total_amount": "10.00",
        "transaction_date": "2026-07-10T12:00:00Z",
        "payers": [{"user_id": u1.id, "amount": "10.00"}],
        "splits": [{"user_id": u1.id, "split_method": "equal", "input_value": "0"}],
    }
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/", json=payload, headers=setup_data["headers1"]
    )
    assert res.status_code == 422

    payload["title"] = "Título normal"
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/", json=payload, headers=setup_data["headers1"]
    )
    assert res.status_code == 200
