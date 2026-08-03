"""A despesa que espelha a parcela de financiamento: moeda, data e imutabilidade.

`pay_installment` montava a `Transaction` à mão, fora do pipeline de conversão
(ADR 0015) e com a data de VENCIMENTO. Dois defeitos saíam daí:

- parcela em USD paga num workspace BRL gravava `currency="USD"`, e como toda
  agregação de workspace filtra `currency == base`, a despesa existia no banco e
  **nenhuma tela a somava** — sem erro e sem aviso;
- a despesa caía no mês do vencimento, então pagar adiantado zerava o caixa do
  mês em que o dinheiro saiu.

E, uma vez criado o vínculo, ele não pode ser editado livremente: a dedup do
caixa escolhe entre contar a despesa OU a parcela, e as duas precisam continuar
falando do mesmo pagamento.
"""
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.jwt import create_access_token
from app.main import app
from app.models.exchange_rate import ExchangeRate
from app.models.transaction import Transaction
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole

client = TestClient(app)


@pytest.fixture(name="cena")
def cena_fixture(db_session: Session, override_get_session):
    user = User(name="Dona", email="parcela-vinculo@t.com", password_hash="h")
    db_session.add(user)
    workspace = Workspace(name="Casa BRL", base_currency="BRL")
    db_session.add(workspace)
    db_session.flush()
    db_session.add(WorkspaceMembership(
        workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.owner
    ))
    db_session.add(ExchangeRate(
        currency="USD", rate_date=date(2026, 3, 10),
        rate=Decimal("5.000000"), source="ptax",
    ))
    db_session.commit()
    token = create_access_token(data={"sub": str(user.id)})
    return {
        "ws_id": workspace.id,
        "user_id": user.id,
        "headers": {"Cookie": f"access_token={token}"},
    }


def _criar_financiamento(cena, moeda="BRL"):
    res = client.post(
        "/api/v1/me/financing",
        json={
            "title": "Imóvel",
            "total_amount": "1000.00",
            "interest_rate": "0.01",
            "start_date": "2026-01-31",
            "installments_count": 10,
            "method": "SAC",
            "currency": moeda,
        },
        headers=cena["headers"],
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


def test_parcela_estrangeira_entra_convertida_na_moeda_base(db_session, cena):
    fin_id = _criar_financiamento(cena, moeda="USD")

    res = client.post(
        f"/api/v1/me/financing/{fin_id}/installments/1/pay",
        json={"workspace_id": cena["ws_id"], "paid_at": "2026-03-10T12:00:00Z"},
        headers=cena["headers"],
    )
    assert res.status_code == 200, res.text
    tx = db_session.get(Transaction, res.json()["transaction_id"])

    # A despesa nasce na BASE do workspace, não na moeda do financiamento —
    # senão ela some de dívidas, relatórios e previsão sem nenhum sinal.
    assert tx.currency == "BRL"
    assert tx.original_currency == "USD"
    assert tx.exchange_rate == Decimal("5.000000")
    assert tx.total_amount == tx.original_amount * Decimal("5")
    # Parcela não é compra no cartão: sem IOF.
    assert tx.iof_rate == Decimal("0")
    # Pagador e divisão acompanham o valor CONVERTIDO
    assert tx.payers[0].amount == tx.total_amount
    assert tx.splits[0].computed_amount == tx.total_amount


def test_vinculo_da_parcela_nao_aceita_edicao_de_valor_ou_data(db_session, cena):
    fin_id = _criar_financiamento(cena)
    res = client.post(
        f"/api/v1/me/financing/{fin_id}/installments/1/pay",
        json={"workspace_id": cena["ws_id"], "paid_at": "2026-03-10T12:00:00Z"},
        headers=cena["headers"],
    )
    tx_id = res.json()["transaction_id"]
    base = f"/api/v1/workspaces/{cena['ws_id']}/transactions/{tx_id}"

    # Mover a data faria a despesa e a parcela caírem em meses diferentes, e a
    # dedup do caixa conta uma OU outra.
    res = client.put(base, json={"transaction_date": "2026-09-01T12:00:00Z"}, headers=cena["headers"])
    assert res.status_code == 409, res.text
    assert "parcela" in res.json()["error"]["message"].lower()

    res = client.put(base, json={"total_amount": "999.00"}, headers=cena["headers"])
    assert res.status_code == 409

    # Renomear continua liberado: isso é sobre COMO a casa registra a parcela.
    res = client.put(base, json={"title": "Parcela do apê"}, headers=cena["headers"])
    assert res.status_code == 200, res.text

    db_session.expire_all()
    assert db_session.get(Transaction, tx_id).title == "Parcela do apê"


def test_desfazer_o_pagamento_remove_a_despesa_vinculada(db_session, cena):
    """O caminho legítimo para corrigir: desfaz no financiamento e refaz."""
    fin_id = _criar_financiamento(cena)
    res = client.post(
        f"/api/v1/me/financing/{fin_id}/installments/1/pay",
        json={"workspace_id": cena["ws_id"]},
        headers=cena["headers"],
    )
    tx_id = res.json()["transaction_id"]

    res = client.post(
        f"/api/v1/me/financing/{fin_id}/installments/1/unpay", headers=cena["headers"]
    )
    assert res.status_code == 200, res.text

    db_session.expire_all()
    assert db_session.get(Transaction, tx_id).deleted_at is not None
    vivas = db_session.exec(
        select(Transaction).where(
            Transaction.workspace_id == cena["ws_id"],
            Transaction.deleted_at.is_(None),
        )
    ).all()
    assert vivas == []
