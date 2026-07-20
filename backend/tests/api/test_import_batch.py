"""Importação em lote com decisão por linha e fingerprint idempotente (ADR 0008)."""
from fastapi.testclient import TestClient
from sqlmodel import select

from app.main import app
from app.models.transaction import Transaction

client = TestClient(app)


def _commit(ws_id, headers, rows, filename="extrato.csv"):
    return client.post(
        f"/api/v1/workspaces/{ws_id}/imports/commit",
        json={"filename": filename, "rows": rows},
        headers=headers,
    )


def test_commit_cria_transacoes_com_pagador(db_session, setup_data, override_get_session):
    ws, headers = setup_data["ws1"], setup_data["headers1"]
    rows = [
        {"line": 2, "title": "Mercado", "total_amount": 50.0, "transaction_date": "2026-03-01T00:00:00"},
        {"line": 3, "title": "Farmácia", "total_amount": 30.0, "transaction_date": "2026-03-02T00:00:00"},
    ]
    resp = _commit(ws.id, headers, rows)
    assert resp.status_code == 200, resp.text
    assert resp.json()["imported"] == 2

    txs = db_session.exec(select(Transaction).where(Transaction.workspace_id == ws.id)).all()
    assert len(txs) == 2
    # Não são nuas: cada uma tem pagador e divisão
    for tx in txs:
        assert len(tx.payers) == 1 and len(tx.splits) == 1
        assert tx.billing_month == "2026-03"


def test_reimportar_mesmo_arquivo_nao_duplica(db_session, setup_data, override_get_session):
    ws, headers = setup_data["ws1"], setup_data["headers1"]
    rows = [
        {"title": "Mercado", "total_amount": 50.0, "transaction_date": "2026-03-01T00:00:00"},
    ]
    first = _commit(ws.id, headers, rows).json()
    assert first["imported"] == 1

    second = _commit(ws.id, headers, rows).json()
    assert second["imported"] == 0
    assert second["duplicate"] == 1

    txs = db_session.exec(select(Transaction).where(Transaction.workspace_id == ws.id)).all()
    assert len(txs) == 1  # não duplicou


def test_decisao_ignorar_e_valor_invalido(db_session, setup_data, override_get_session):
    ws, headers = setup_data["ws1"], setup_data["headers1"]
    rows = [
        {"title": "Manter", "total_amount": 10.0, "transaction_date": "2026-03-01T00:00:00", "decision": "import"},
        {"title": "Descartar", "total_amount": 20.0, "transaction_date": "2026-03-02T00:00:00", "decision": "ignore"},
        {"title": "Negativa", "total_amount": -5.0, "transaction_date": "2026-03-03T00:00:00", "decision": "import"},
    ]
    resp = _commit(ws.id, headers, rows).json()
    assert resp["imported"] == 1
    assert resp["ignored"] == 1
    assert resp["skipped"] == 1

    txs = db_session.exec(select(Transaction).where(Transaction.workspace_id == ws.id)).all()
    assert len(txs) == 1
    assert txs[0].title == "Manter"


def test_titulos_diferentes_nao_sao_duplicata(db_session, setup_data, override_get_session):
    ws, headers = setup_data["ws1"], setup_data["headers1"]
    rows = [
        {"title": "A", "total_amount": 50.0, "transaction_date": "2026-03-01T00:00:00"},
        {"title": "B", "total_amount": 50.0, "transaction_date": "2026-03-01T00:00:00"},
    ]
    resp = _commit(ws.id, headers, rows).json()
    assert resp["imported"] == 2  # mesmo valor/data, títulos distintos → não duplica
