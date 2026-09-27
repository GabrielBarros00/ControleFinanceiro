"""A listagem de lançamentos faz o mesmo número de consultas com 10 ou 100 linhas.

Auditoria 2026-09-26, P1 (o F2 da auditoria de 2026-08-29): a rota devolvia os
objetos do ORM e a serialização carregava cada relacionamento sob demanda — uma
consulta por linha para pagadores, divisão, itens (e a divisão de cada item),
ajustes, tags e estabelecimento. `limit=100` custava 533 consultas e 537 ms. É a
rota mais chamada do app: aparece em várias telas e no bootstrap.

O cuidado de medição: a suíte serve a rota com a MESMA sessão do teste, e um
relacionamento já carregado no mapa de identidade não gera consulta — o N+1
ficaria invisível. Daí o `expire_all()` antes de cada chamada.
"""
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.main import app
from app.models.merchant import Merchant
from app.models.tag import Tag, TransactionTagLink
from app.models.transaction import (
    SplitMethod,
    Transaction,
    TransactionAdjustment,
    TransactionItem,
    TransactionItemShare,
    TransactionPayer,
    TransactionSplit,
)


@pytest.fixture(name="client")
def client_fixture(override_get_session):
    return TestClient(app)


def _lancamentos_completos(db, ws, user, quantos: int, mes: str) -> None:
    """Lançamentos com TODOS os relacionamentos que a listagem serializa."""
    tag = Tag(workspace_id=ws.id, name=f"tag-{mes}")
    loja = Merchant(workspace_id=ws.id, name=f"Loja {mes}")
    db.add_all([tag, loja])
    db.commit()
    for i in range(quantos):
        tx = Transaction(
            title=f"Compra {i}", total_amount=Decimal("10.00"), billing_month=mes,
            transaction_date=datetime(int(mes[:4]), int(mes[5:]), 10, 15, tzinfo=UTC),
            workspace_id=ws.id, created_by_user_id=user.id, merchant_id=loja.id,
        )
        db.add(tx)
        db.flush()
        item = TransactionItem(transaction_id=tx.id, title="Item", amount=Decimal("10.00"))
        db.add(item)
        db.flush()
        db.add_all([
            TransactionPayer(transaction_id=tx.id, user_id=user.id, amount=Decimal("10.00")),
            TransactionSplit(transaction_id=tx.id, user_id=user.id, split_method=SplitMethod.equal,
                             input_value=Decimal("0"), computed_amount=Decimal("10.00")),
            TransactionItemShare(item_id=item.id, user_id=user.id, split_method=SplitMethod.equal,
                                 input_value=Decimal("0"), computed_amount=Decimal("10.00")),
            TransactionAdjustment(transaction_id=tx.id, amount=Decimal("0.00")),
            TransactionTagLink(transaction_id=tx.id, tag_id=tag.id),
        ])
    db.commit()


def _consultas(client, db, url: str, headers) -> tuple[int, dict]:
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


def test_consultas_nao_crescem_com_o_numero_de_linhas(client, db_session, setup_data):
    ws, u1, headers = setup_data["ws1"], setup_data["u1"], setup_data["headers1"]
    _lancamentos_completos(db_session, ws, u1, 10, "2026-05")
    _lancamentos_completos(db_session, ws, u1, 100, "2026-06")
    base = f"/api/v1/workspaces/{ws.id}/transactions/"
    # A primeira chamada paga um custo único (leituras que ficam em cache no
    # processo); medir a partir da segunda compara só o que depende das linhas.
    _consultas(client, db_session, f"{base}?month=2026-01", headers)

    dez, corpo_dez = _consultas(client, db_session, f"{base}?month=2026-05&limit=100", headers)
    cem, corpo_cem = _consultas(client, db_session, f"{base}?month=2026-06&limit=100", headers)

    assert len(corpo_dez["items"]) == 10 and len(corpo_cem["items"]) == 100
    # A medição enxerga as linhas: cada relacionamento veio preenchido.
    linha = corpo_cem["items"][0]
    assert len(linha["payers"]) == 1 and len(linha["splits"]) == 1
    assert len(linha["items"]) == 1 and len(linha["items"][0]["shares"]) == 1
    assert len(linha["adjustments"]) == 1 and len(linha["tags"]) == 1
    assert linha["merchant"]["name"] == "Loja 2026-06"

    assert cem == dez, f"10 linhas: {dez} consultas; 100 linhas: {cem}"
    # Teto folgado para o custo fixo (sessão, escopo, recorrência, contagem,
    # soma, página e um SELECT por relacionamento). Antes: 533 com 100 linhas.
    assert cem <= 20, cem
