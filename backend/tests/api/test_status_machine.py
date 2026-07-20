"""Máquina de estados de status + timestamps (ADR 0003).

draft→pending→confirmed→paid; *→cancelled (exceto paid); paid→confirmed=reabrir;
cancelled é terminal. Cada transição carimba seu timestamp; toda edição
atualiza updated_at.
"""
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import app
from app.models.transaction import Transaction

client = TestClient(app)


def _create(setup_data, **overrides):
    ws1, u1 = setup_data["ws1"], setup_data["u1"]
    payload = {
        "title": "Status Tx",
        "total_amount": 10.0,
        "transaction_date": "2026-05-10T10:00:00",
        "payers": [{"user_id": u1.id, "amount": 10.0}],
        "splits": [{"user_id": u1.id, "split_method": "equal", "input_value": 0}],
    }
    payload.update(overrides)
    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/",
        json=payload,
        headers=setup_data["headers1"],
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _put_status(setup_data, tx_id, status):
    return client.put(
        f"/api/v1/workspaces/{setup_data['ws1'].id}/transactions/{tx_id}",
        json={"status": status},
        headers=setup_data["headers1"],
    )


def test_criacao_confirmada_carimba_confirmed_at(db_session: Session, setup_data, override_get_session):
    data = _create(setup_data)  # default: confirmed
    tx = db_session.get(Transaction, data["id"])
    assert tx.confirmed_at is not None
    assert tx.paid_at is None
    assert tx.cancelled_at is None


def test_pagar_e_reabrir_carimba_e_limpa_paid_at(db_session: Session, setup_data, override_get_session):
    data = _create(setup_data)
    tx_id = data["id"]

    resp = _put_status(setup_data, tx_id, "paid")
    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    tx = db_session.get(Transaction, tx_id)
    assert tx.paid_at is not None

    resp = _put_status(setup_data, tx_id, "confirmed")  # reabrir
    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    tx = db_session.get(Transaction, tx_id)
    assert tx.paid_at is None
    assert tx.confirmed_at is not None


def test_transicao_invalida_retorna_409(setup_data, override_get_session):
    data = _create(setup_data)
    tx_id = data["id"]

    # confirmed → draft não existe na máquina
    resp = _put_status(setup_data, tx_id, "draft")
    assert resp.status_code == 409
    assert "Transição de status inválida" in resp.json()["error"]["message"]

    # paid → cancelled exige reabrir antes
    assert _put_status(setup_data, tx_id, "paid").status_code == 200
    resp = _put_status(setup_data, tx_id, "cancelled")
    assert resp.status_code == 409


def test_cancelada_e_terminal(db_session: Session, setup_data, override_get_session):
    data = _create(setup_data)
    tx_id = data["id"]

    resp = _put_status(setup_data, tx_id, "cancelled")
    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    assert db_session.get(Transaction, tx_id).cancelled_at is not None

    # Nem edição de campos nem nova transição
    resp = client.put(
        f"/api/v1/workspaces/{setup_data['ws1'].id}/transactions/{tx_id}",
        json={"title": "Renomeada"},
        headers=setup_data["headers1"],
    )
    assert resp.status_code == 409
    assert _put_status(setup_data, tx_id, "confirmed").status_code == 409


def test_edicao_atualiza_updated_at(db_session: Session, setup_data, override_get_session):
    data = _create(setup_data)
    tx_id = data["id"]
    before = db_session.get(Transaction, tx_id).updated_at

    resp = client.put(
        f"/api/v1/workspaces/{setup_data['ws1'].id}/transactions/{tx_id}",
        json={"title": "Editada"},
        headers=setup_data["headers1"],
    )
    assert resp.status_code == 200
    db_session.expire_all()
    after = db_session.get(Transaction, tx_id).updated_at
    assert after > before


def test_fluxo_draft_pending_confirmed(db_session: Session, setup_data, override_get_session):
    data = _create(setup_data, status="draft")
    tx_id = data["id"]
    tx = db_session.get(Transaction, tx_id)
    assert tx.confirmed_at is None

    assert _put_status(setup_data, tx_id, "pending").status_code == 200
    assert _put_status(setup_data, tx_id, "confirmed").status_code == 200
    db_session.expire_all()
    assert db_session.get(Transaction, tx_id).confirmed_at is not None
