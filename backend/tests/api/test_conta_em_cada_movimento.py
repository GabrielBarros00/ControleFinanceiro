"""Todo movimento de caixa sabe dizer de qual conta saiu (ADR 0034).

O saldo só existe para o que declara conta. Este arquivo cobre as três origens que
ganharam a coluna nesta onda — recorrência, parcela de financiamento e acerto — e
o vazamento que a auditoria encontrou no caminho da recorrência:

> `sync_current_month` apaga os filhos do lançamento e os recria. Sem repassar o
> `account_id`, editar o template de uma despesa fixa apagava em silêncio a conta
> da instância do mês, e o saldo mudava sem ninguém ter tocado no saldo.

E a regra de privacidade que atravessa os três: **cada um declara a SUA conta**.
Registrar que "o Bob pagou" é informação legítima de um membro; afirmar de qual
conta bancária do Bob o dinheiro saiu não é.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.jwt import create_access_token
from app.domain.dates import today_local
from app.main import app
from app.models.recurring import RecurrenceFrequency, RecurringExpense
from app.models.transaction import Transaction, TransactionPayer
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole

client = TestClient(app)

HOJE = today_local()
ONTEM = HOJE - timedelta(days=1)


@pytest.fixture(name="cena")
def cena_fixture(db_session: Session, override_get_session):
    dono = User(name="Dona", email="conta_mov@t.com", password_hash="h",
                report_currency="BRL")
    outro = User(name="Colega", email="colega_mov@t.com", password_hash="h",
                 report_currency="BRL")
    db_session.add_all([dono, outro])
    ws = Workspace(name="Casa", base_currency="BRL")
    db_session.add(ws)
    db_session.flush()
    db_session.add_all([
        WorkspaceMembership(workspace_id=ws.id, user_id=dono.id, role=WorkspaceRole.owner),
        WorkspaceMembership(workspace_id=ws.id, user_id=outro.id, role=WorkspaceRole.member),
    ])
    db_session.commit()
    db_session.refresh(dono)
    db_session.refresh(outro)
    return {
        "db": db_session, "ws_id": ws.id,
        "dono": dono.id, "outro": outro.id,
        "headers": {"Cookie": f"access_token={create_access_token({'sub': str(dono.id)})}"},
        "headers_outro": {
            "Cookie": f"access_token={create_access_token({'sub': str(outro.id)})}"
        },
    }


def _conta(cena, nome="Nubank", moeda="BRL", headers=None):
    r = client.post(
        "/api/v1/me/payment-accounts",
        json={"name": nome, "type": "checking", "currency": moeda},
        headers=headers or cena["headers"],
    )
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# 1. Recorrência


def _template(cena, conta_id=None):
    t = RecurringExpense(
        title="Internet", base_amount=Decimal("120.00"), currency="BRL",
        frequency=RecurrenceFrequency.monthly, day_of_month=1,
        workspace_id=cena["ws_id"], created_by_user_id=cena["dono"],
        payer_user_id=cena["dono"], account_id=conta_id, auto_settle=True,
    )
    cena["db"].add(t)
    cena["db"].commit()
    cena["db"].refresh(t)
    return t


def _payers(cena):
    return cena["db"].exec(
        select(TransactionPayer)
        .join(Transaction, Transaction.id == TransactionPayer.transaction_id)
        .where(Transaction.workspace_id == cena["ws_id"])
    ).all()


def test_ocorrencia_nasce_com_a_conta_do_template(cena):
    """Débito automático é o caso em que a pessoa MENOS vai abrir o lançamento
    para declarar a conta — então o template a declara uma vez."""
    conta = _conta(cena)
    _template(cena, conta["id"])

    r = client.get(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/", headers=cena["headers"]
    )
    assert r.status_code == 200, r.text

    cena["db"].expire_all()
    pagadores = _payers(cena)
    assert pagadores, "a materialização não criou nada"
    assert all(p.account_id == conta["id"] for p in pagadores)


def test_editar_o_template_nao_apaga_a_conta_da_instancia(cena):
    """O vazamento que a auditoria encontrou.

    `sync_current_month` apaga os filhos e os recria; sem repassar a conta, a
    edição de um valor derrubava o saldo sem nenhum movimento que explicasse.
    """
    conta = _conta(cena)
    template = _template(cena, conta["id"])
    client.get(f"/api/v1/workspaces/{cena['ws_id']}/transactions/", headers=cena["headers"])

    r = client.put(
        f"/api/v1/workspaces/{cena['ws_id']}/recurring/{template.id}",
        json={"base_amount": "150.00"},
        params={"scope": "all"},
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text

    cena["db"].expire_all()
    pagadores = _payers(cena)
    assert pagadores
    assert all(p.account_id == conta["id"] for p in pagadores), (
        "editar o template apagou a conta da instância"
    )


def test_conta_invalida_no_template_nao_derruba_a_materializacao(cena):
    """A conta é revalidada a cada ocorrência: entre o cadastro e o mês que vem
    ela pode ter sido desativada. A ocorrência nasce SEM conta, não deixa de
    nascer."""
    conta = _conta(cena)
    _template(cena, conta["id"])
    client.put(
        f"/api/v1/me/payment-accounts/{conta['id']}",
        json={"active": False},
        headers=cena["headers"],
    )

    r = client.get(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/", headers=cena["headers"]
    )
    assert r.status_code == 200, r.text
    cena["db"].expire_all()
    pagadores = _payers(cena)
    assert pagadores, "a ocorrência tem de nascer mesmo assim"
    assert all(p.account_id is None for p in pagadores)


# ---------------------------------------------------------------------------
# 2. Financiamento


def _financiamento(cena):
    r = client.post(
        "/api/v1/me/financing",
        json={
            "title": "Carro", "total_amount": "12000.00", "interest_rate": "0.01",
            "start_date": (HOJE - timedelta(days=60)).isoformat(),
            "installments_count": 12, "method": "PRICE", "currency": "BRL",
        },
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_parcela_paga_com_conta_move_o_saldo(cena):
    conta = _conta(cena)
    client.put(
        f"/api/v1/me/payment-accounts/{conta['id']}/opening-balance",
        json={"amount": "10000.00", "as_of": ONTEM.isoformat()},
        headers=cena["headers"],
    )
    fin = _financiamento(cena)

    r = client.post(
        f"/api/v1/me/financing/{fin['id']}/installments/1/pay",
        json={"account_id": conta["id"]},
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text

    saldo = client.get("/api/v1/me/balance", headers=cena["headers"]).json()
    assert Decimal(saldo["total"]) < Decimal("10000.00"), (
        "a parcela paga tem de sair da conta"
    )
    assert saldo["unassigned_movements"] == 0


def test_parcela_com_conta_de_outra_moeda_e_recusada(cena):
    conta = _conta(cena, "Wise", "USD")
    fin = _financiamento(cena)
    r = client.post(
        f"/api/v1/me/financing/{fin['id']}/installments/1/pay",
        json={"account_id": conta["id"]},
        headers=cena["headers"],
    )
    assert r.status_code == 400
    assert "USD" in r.json()["error"]["message"]

    # A recusa não pode deixar a parcela marcada como paga.
    parcelas = client.get(
        f"/api/v1/me/financing/{fin['id']}/schedule", headers=cena["headers"]
    ).json()
    assert all(not p["is_paid"] for p in parcelas)


# ---------------------------------------------------------------------------
# 3. Acerto — cada um declara a SUA conta


def _cria_divida(cena):
    """O acerto exige dívida REAL na direção (ADR 0009): o colega adianta R$ 400
    numa despesa de que o dono consome metade, e o dono passa a dever 200."""
    from app.domain.dates import civil_instant, month_key

    r = client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/",
        json={
            "title": "Mercado", "total_amount": "400.00",
            "transaction_date": civil_instant(ONTEM).isoformat(),
            "billing_month": month_key(ONTEM),
            "payers": [{"user_id": cena["outro"], "amount": "400.00"}],
            "splits": [
                {"user_id": cena["dono"], "split_method": "fixed", "input_value": "200.00"},
                {"user_id": cena["outro"], "split_method": "fixed", "input_value": "200.00"},
            ],
        },
        headers=cena["headers_outro"],
    )
    assert r.status_code == 200, r.text


def _acerto(cena, **extra):
    _cria_divida(cena)
    return client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/settlements",
        json={
            "from_user_id": cena["dono"], "to_user_id": cena["outro"],
            "amount": "200.00", **extra,
        },
        headers=cena["headers"],
    )


def test_pagador_declara_a_propria_conta_no_acerto(cena):
    conta = _conta(cena)
    client.put(
        f"/api/v1/me/payment-accounts/{conta['id']}/opening-balance",
        json={"amount": "1000.00", "as_of": ONTEM.isoformat()},
        headers=cena["headers"],
    )

    r = _acerto(cena, from_account_id=conta["id"])
    assert r.status_code == 200, r.text

    saldo = client.get("/api/v1/me/balance", headers=cena["headers"]).json()
    assert Decimal(saldo["total"]) == Decimal("800.00")


def test_ninguem_declara_a_conta_de_outra_pessoa(cena):
    """A regra que o projeto já escreveu em `_validate_payer_accounts`.

    O gate é ANTERIOR ao da dívida: a recusa não depende de haver o que acertar,
    porque o problema não é o valor — é quem está afirmando o quê.
    """
    conta_do_outro = _conta(cena, "Itaú do colega", headers=cena["headers_outro"])

    r = client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/settlements",
        json={
            "from_user_id": cena["outro"], "to_user_id": cena["dono"],
            "amount": "200.00", "from_account_id": conta_do_outro["id"],
        },
        headers=cena["headers"],  # o DONO registrando o acerto do colega
    )
    assert r.status_code == 400
    assert "outra pessoa" in r.json()["error"]["message"]


def test_credor_declara_a_conta_dele_por_porta_propria(cena):
    """Sem esta porta, o acerto recebido seria para sempre um movimento sem conta
    no saldo de quem recebeu — visível no contador e impossível de corrigir."""
    r = _acerto(cena)
    assert r.status_code == 200, r.text
    acerto_id = r.json()["id"]

    conta = _conta(cena, "Conta do colega", headers=cena["headers_outro"])
    client.put(
        f"/api/v1/me/payment-accounts/{conta['id']}/opening-balance",
        json={"amount": "0.00", "as_of": ONTEM.isoformat()},
        headers=cena["headers_outro"],
    )

    atribui = client.put(
        f"/api/v1/me/settlements/{acerto_id}/account",
        json={"account_id": conta["id"]},
        headers=cena["headers_outro"],
    )
    assert atribui.status_code == 200, atribui.text

    saldo = client.get("/api/v1/me/balance", headers=cena["headers_outro"]).json()
    assert Decimal(saldo["total"]) == Decimal("200.00")


def test_so_o_credor_atribui_a_conta_do_recebimento(cena):
    """404 e não 403 (anti-enumeração): quem não é o credor não fica sabendo nem
    que o acerto existe."""
    r = _acerto(cena)
    acerto_id = r.json()["id"]
    conta = _conta(cena)

    negado = client.put(
        f"/api/v1/me/settlements/{acerto_id}/account",
        json={"account_id": conta["id"]},
        headers=cena["headers"],  # o PAGADOR tentando declarar o lado do credor
    )
    assert negado.status_code == 404
