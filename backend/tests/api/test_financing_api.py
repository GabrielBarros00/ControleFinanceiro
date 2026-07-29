"""Pagar uma parcela de financiamento gera uma DESPESA real (FIN-101)."""
from fastapi.testclient import TestClient
from sqlmodel import select

from app.main import app
from app.models.transaction import Transaction

client = TestClient(app)


def _create_financing(ws_id, headers):
    return client.post(
        f"/api/v1/workspaces/{ws_id}/financing",
        json={
            "title": "Carro",
            "total_amount": 1200.0,
            "interest_rate": 0.01,
            "start_date": "2026-01-31",
            "installments_count": 12,
            "method": "SAC",
        },
        headers=headers,
    )


def test_pagar_parcela_gera_transacao(db_session, setup_data, override_get_session):
    ws, headers = setup_data["ws1"], setup_data["headers1"]
    resp = _create_financing(ws.id, headers)
    assert resp.status_code == 200, resp.text
    fin_id = resp.json()["id"]

    # Cronograma: 1ª parcela vence em fev (mês de calendário a partir de 31/jan)
    schedule = client.get(f"/api/v1/workspaces/{ws.id}/financing/{fin_id}/schedule", headers=headers).json()
    first = schedule[0]

    resp = client.post(
        f"/api/v1/workspaces/{ws.id}/financing/{fin_id}/installments/1/pay",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    tx_id = resp.json()["transaction_id"]
    assert tx_id is not None

    db_session.expire_all()
    tx = db_session.get(Transaction, tx_id)
    assert tx is not None
    assert str(tx.total_amount) == str(first["total_amount"])
    assert tx.billing_month == first["due_date"][:7]  # YYYY-MM da data de vencimento
    # Tem pagador e divisão → não é transação nua (entra em caixa/relatórios)
    assert len(tx.payers) == 1
    assert len(tx.splits) == 1
    assert tx.payers[0].user_id == setup_data["u1"].id


def test_pagar_parcela_ja_paga_falha(db_session, setup_data, override_get_session):
    ws, headers = setup_data["ws1"], setup_data["headers1"]
    fin_id = _create_financing(ws.id, headers).json()["id"]
    client.post(f"/api/v1/workspaces/{ws.id}/financing/{fin_id}/installments/1/pay", headers=headers)
    resp = client.post(f"/api/v1/workspaces/{ws.id}/financing/{fin_id}/installments/1/pay", headers=headers)
    assert resp.status_code == 400
    # Não cria uma segunda transação para a mesma parcela
    txs = db_session.exec(select(Transaction).where(Transaction.workspace_id == ws.id)).all()
    assert len(txs) == 1


def test_estorno_encontra_a_despesa_mesmo_apos_renomear(db_session, setup_data, override_get_session):
    """O estorno vincula por ID, não pelo título do financiamento.

    Pelo título, renomear o financiamento (que é permitido, e não trava com
    parcelas pagas) fazia o `unpay` não achar a despesa: a parcela voltava a
    aberta e o gasto ficava PARA SEMPRE no caixa e nos relatórios.
    """
    ws, headers = setup_data["ws1"], setup_data["headers1"]
    fin_id = _create_financing(ws.id, headers).json()["id"]

    pago = client.post(
        f"/api/v1/workspaces/{ws.id}/financing/{fin_id}/installments/1/pay", headers=headers
    )
    tx_id = pago.json()["transaction_id"]

    # Renomeia DEPOIS de pagar — só o título, então o cronograma não é regerado
    renomeado = client.put(
        f"/api/v1/workspaces/{ws.id}/financing/{fin_id}",
        json={"title": "Carro novo"},
        headers=headers,
    )
    assert renomeado.status_code == 200, renomeado.text

    estorno = client.post(
        f"/api/v1/workspaces/{ws.id}/financing/{fin_id}/installments/1/unpay", headers=headers
    )
    assert estorno.status_code == 200, estorno.text

    db_session.expire_all()
    tx = db_session.get(Transaction, tx_id)
    assert tx.deleted_at is not None, "a despesa da parcela sobreviveu ao estorno"


def test_estorno_nao_apaga_despesa_homonima(db_session, setup_data, override_get_session):
    """Uma despesa manual com o mesmo título não pode sumir junto com o estorno."""
    from decimal import Decimal

    ws, headers = setup_data["ws1"], setup_data["headers1"]
    fin_id = _create_financing(ws.id, headers).json()["id"]
    client.post(
        f"/api/v1/workspaces/{ws.id}/financing/{fin_id}/installments/1/pay", headers=headers
    )

    homonima = Transaction(
        title="Carro — Parcela 1/12",
        total_amount=Decimal("10.00"),
        billing_month="2026-02",
        workspace_id=ws.id,
        created_by_user_id=setup_data["u1"].id,
    )
    db_session.add(homonima)
    db_session.commit()
    db_session.refresh(homonima)

    client.post(
        f"/api/v1/workspaces/{ws.id}/financing/{fin_id}/installments/1/unpay", headers=headers
    )

    db_session.expire_all()
    assert db_session.get(Transaction, homonima.id).deleted_at is None
