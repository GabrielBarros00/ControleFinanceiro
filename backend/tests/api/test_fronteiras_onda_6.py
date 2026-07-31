"""Fronteiras que a Onda 5 deixou pela metade (auditoria de 2026-07-31).

Três regras que existiam pela metade e falhavam em silêncio:

- remover um membro conferia o passado (dívida em aberto) e não o FUTURO
  (recorrência ativa em que ele é pagador ou participante) — a ocorrência
  seguinte era descartada sem aviso e o aluguel parava de aparecer;
- qualquer membro podia declarar de qual conta bancária PRIVADA de outra pessoa
  o dinheiro saiu, bastando pôr essa pessoa como pagadora.
"""
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.core.jwt import create_access_token
from app.main import app
from app.models.user import User

client = TestClient(app)

HOJE = datetime.now(UTC).date()
MES = datetime.now(UTC).strftime("%Y-%m")
QUANDO = datetime.now(UTC).replace(day=10, hour=12, minute=0, second=0, microsecond=0)


def _h(user: User) -> dict:
    return {"Cookie": f"access_token={create_access_token({'sub': str(user.id)})}"}


def _registra(db_session, nome, email):
    res = client.post(
        "/api/v1/auth/register",
        json={"name": nome, "email": email, "password": "senha123"},
    )
    assert res.status_code == 200, res.text
    user = db_session.exec(select(User).where(User.email == email)).first()
    headers = _h(user)
    ws = client.get("/api/v1/workspaces/", headers=headers).json()[0]["id"]
    return {"user": user, "headers": headers, "ws": ws}


def _convida(dono, convidado, papel="member"):
    client.post(
        f"/api/v1/workspaces/{dono['ws']}/invites",
        json={"email": convidado["user"].email, "role": papel},
        headers=dono["headers"],
    )
    avisos = client.get("/api/v1/notifications", headers=convidado["headers"]).json()
    token = next(n["invite_token"] for n in avisos["items"] if n.get("invite_token"))
    res = client.post(f"/api/v1/invites/accept/{token}", headers=convidado["headers"])
    assert res.status_code == 200, res.text


@pytest.fixture(name="casa")
def casa_fixture(db_session, override_get_session):
    dono = _registra(db_session, "Alice", "alice-f6@ov.com")
    colega = _registra(db_session, "Bob", "bob-f6@ov.com")
    _convida(dono, colega)
    return {"dono": dono, "colega": colega, "ws": dono["ws"]}


# ---------------------------------------------------------------------------
# Remover membro × recorrência ativa

def _cria_recorrencia(casa, payer_user_id, participantes):
    """Recorrência que ainda NÃO materializou nada.

    `start_date` no futuro de propósito: com uma ocorrência já materializada, a
    despesa gerada cria dívida real e `_ensure_no_open_balance` recusa a remoção
    primeiro — mascarando justamente a trava que este arquivo testa. O caso que
    interessa é o do compromisso que só existe no futuro.
    """
    futuro = date(HOJE.year + 1, 1, 5)
    res = client.post(
        f"/api/v1/workspaces/{casa['ws']}/recurring",
        json={
            "title": "Aluguel",
            "base_amount": "2000.00",
            "frequency": "monthly",
            "day_of_month": 5,
            "start_date": futuro.isoformat(),
            "payer_user_id": payer_user_id,
            "split_snapshot": [
                {"user_id": uid, "split_method": "percentage", "input_value": "50.00"}
                for uid in participantes
            ],
        },
        headers=casa["dono"]["headers"],
    )
    assert res.status_code in (200, 201), res.text
    return res.json()


def test_nao_remove_membro_com_recorrencia_ativa(casa):
    """Sem esta trava, a próxima materialização descarta a ocorrência calada."""
    alice, bob = casa["dono"]["user"], casa["colega"]["user"]
    _cria_recorrencia(casa, alice.id, [alice.id, bob.id])

    res = client.delete(
        f"/api/v1/workspaces/{casa['ws']}/members/{bob.id}",
        headers=casa["dono"]["headers"],
    )
    assert res.status_code == 409, res.text
    detalhe = res.json()["error"]["message"]
    assert "Aluguel" in detalhe
    assert "recorrência" in detalhe.lower()


def test_nao_deixa_sair_quem_e_pagador_de_recorrencia_ativa(casa):
    """Mesma regra na saída voluntária — senão basta sair em vez de ser removido."""
    bob = casa["colega"]["user"]
    _cria_recorrencia(casa, bob.id, [bob.id])

    res = client.post(
        f"/api/v1/workspaces/{casa['ws']}/leave", headers=casa["colega"]["headers"]
    )
    assert res.status_code == 409, res.text


def test_recorrencia_desativada_nao_bloqueia(casa):
    """A trava é sobre o que AINDA vai materializar."""
    alice, bob = casa["dono"]["user"], casa["colega"]["user"]
    criada = _cria_recorrencia(casa, alice.id, [alice.id, bob.id])
    client.put(
        f"/api/v1/workspaces/{casa['ws']}/recurring/{criada['id']}",
        json={"is_active": False},
        headers=casa["dono"]["headers"],
    )

    res = client.delete(
        f"/api/v1/workspaces/{casa['ws']}/members/{bob.id}",
        headers=casa["dono"]["headers"],
    )
    assert res.status_code == 200, res.text


def test_membro_sem_recorrencia_sai_normalmente(casa):
    bob = casa["colega"]["user"]
    res = client.delete(
        f"/api/v1/workspaces/{casa['ws']}/members/{bob.id}",
        headers=casa["dono"]["headers"],
    )
    assert res.status_code == 200, res.text


# ---------------------------------------------------------------------------
# Conta bancária de terceiro

def _conta(ctx, nome="Nubank"):
    res = client.post(
        "/api/v1/me/payment-accounts",
        json={"name": nome, "type": "checking"},
        headers=ctx["headers"],
    )
    assert res.status_code in (200, 201), res.text
    return res.json()["id"]


def _lanca(ctx, workspace_id, payers, splits):
    return client.post(
        f"/api/v1/workspaces/{workspace_id}/transactions/",
        json={
            "title": "Mercado",
            "total_amount": "100.00",
            "transaction_date": QUANDO.isoformat(),
            "billing_month": MES,
            "payers": payers,
            "splits": splits,
        },
        headers=ctx["headers"],
    )


def test_nao_declara_conta_bancaria_de_outra_pessoa(casa):
    """A validação conferia só se a conta era do PAGADOR declarado.

    Bastava pôr o Bob como pagador e informar o id de uma conta dele para
    afirmar, no extrato pessoal do Bob, de qual conta bancária o dinheiro saiu —
    informação que só ele tem.
    """
    alice, bob = casa["dono"]["user"], casa["colega"]["user"]
    conta_do_bob = _conta(casa["colega"])

    res = _lanca(
        casa["dono"],
        casa["ws"],
        payers=[{"user_id": bob.id, "amount": "100.00", "account_id": conta_do_bob}],
        splits=[
            {"user_id": alice.id, "split_method": "fixed", "input_value": "50.00"},
            {"user_id": bob.id, "split_method": "fixed", "input_value": "50.00"},
        ],
    )
    assert res.status_code == 400, res.text
    assert "conta de outra pessoa" in res.json()["error"]["message"]


def test_declarar_outro_como_pagador_continua_valendo(casa):
    """Sem a conta, registrar que "o Bob pagou" é informação legítima de um
    membro — e continua permitido (decisão do dono nesta rodada)."""
    alice, bob = casa["dono"]["user"], casa["colega"]["user"]

    res = _lanca(
        casa["dono"],
        casa["ws"],
        payers=[{"user_id": bob.id, "amount": "100.00"}],
        splits=[
            {"user_id": alice.id, "split_method": "fixed", "input_value": "50.00"},
            {"user_id": bob.id, "split_method": "fixed", "input_value": "50.00"},
        ],
    )
    assert res.status_code == 200, res.text


def test_a_propria_conta_continua_valendo(casa):
    alice = casa["dono"]["user"]
    minha_conta = _conta(casa["dono"])

    res = _lanca(
        casa["dono"],
        casa["ws"],
        payers=[{"user_id": alice.id, "amount": "100.00", "account_id": minha_conta}],
        splits=[{"user_id": alice.id, "split_method": "fixed", "input_value": "100.00"}],
    )
    assert res.status_code == 200, res.text
