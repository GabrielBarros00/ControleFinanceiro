"""O onboarding passa a perguntar o que a primeira tela precisa.

## O que estava errado

O onboarding pedia **salário** e **cartão**. Nenhum dos dois é o que a primeira
tela usa para responder a primeira pergunta.

Depois da Onda 2, "Hoje" abre com **"Seu dinheiro"** — e para todo usuário novo
esse bloco dizia *"Saldo ainda não configurado"*, com um convite para ir a outra
tela informar. Ou seja: o app gastava três passos pedindo dados no primeiro
minuto e, no fim deles, a tela inicial ainda começava vazia no lugar mais
importante.

Saldo de abertura é o único dado que o app **não consegue deduzir** de nada: ele
não sai de lançamento, nem de renda, nem de fatura. Salário vira renda no mês
seguinte sozinho (recorrência), e cartão se cadastra na hora de usar. Saldo, não:
sem ele, `/me/balance` devolve `null` e a projeção inteira fica sem chão.

## O que este arquivo tranca

1. O onboarding **cria a conta com saldo de abertura** — e ele é o saldo que a
   tela lê.
2. Ele continua **pulável**: quem não sabe o número agora não fica preso.
3. Salário continua aceito (quem informa não perde o dado), mas deixou de ser
   obrigatório.
"""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.jwt import create_access_token
from app.main import app
from app.models.income import Income
from app.models.payment_account import PaymentAccount
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole

client = TestClient(app)


@pytest.fixture(name="novato")
def novato_fixture(db_session: Session, override_get_session):
    user = User(
        name="Novato", email="novato@onb.com", password_hash="h",
        needs_onboarding=True, report_currency="BRL",
    )
    ws = Workspace(name="Meu espaço", base_currency="BRL")
    db_session.add_all([user, ws])
    db_session.commit()
    db_session.add(WorkspaceMembership(
        workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.owner,
    ))
    db_session.commit()
    db_session.refresh(user)
    return {
        "db": db_session, "user": user,
        "h": {"Cookie": f"access_token={create_access_token({'sub': str(user.id)})}"},
    }


def _concluir(novato, **corpo):
    return client.post("/api/v1/auth/onboarding", json=corpo, headers=novato["h"])


def _contas(novato):
    return novato["db"].exec(
        select(PaymentAccount).where(PaymentAccount.owner_user_id == novato["user"].id)
    ).all()


def test_cria_a_conta_com_o_saldo_informado(novato):
    r = _concluir(novato, account_name="Nubank", account_balance="1500.00")

    assert r.status_code == 200, r.text
    contas = _contas(novato)
    assert len(contas) == 1, f"esperava uma conta criada, veio {len(contas)}"
    assert contas[0].name == "Nubank"


def test_o_saldo_informado_e_o_que_a_primeira_tela_le(novato):
    """O fecho do ciclo: o número tem de chegar em `/me/balance`.

    Criar a conta sem saldo de abertura deixaria a tela exatamente como estava —
    "saldo ainda não configurado" —, só que agora com uma conta vazia no meio.
    """
    _concluir(novato, account_name="Nubank", account_balance="1500.00")

    saldo = client.get("/api/v1/me/balance", headers=novato["h"]).json()

    assert saldo["total"] is not None, (
        "a primeira tela continua sem saber quanto a pessoa tem"
    )
    assert Decimal(str(saldo["total"])) == Decimal("1500.00")


def test_continua_pulavel(novato):
    """Quem não sabe o número agora não pode ficar preso na porta de entrada."""
    r = _concluir(novato)

    assert r.status_code == 200, r.text
    assert _contas(novato) == []
    novato["db"].refresh(novato["user"])
    assert novato["user"].needs_onboarding is False, (
        "pular o onboarding tem de concluí-lo — senão o diálogo volta a cada visita"
    )


def test_saldo_zero_ainda_e_uma_resposta(novato):
    """"Não tenho nada na conta" é diferente de "não quis dizer"."""
    _concluir(novato, account_name="Carteira", account_balance="0")

    saldo = client.get("/api/v1/me/balance", headers=novato["h"]).json()
    assert saldo["total"] is not None
    assert Decimal(str(saldo["total"])) == Decimal("0")


def test_conta_sem_nome_nao_e_criada(novato):
    """Saldo sem conta não existe: o número precisa morar em algum lugar."""
    _concluir(novato, account_balance="900.00")
    assert _contas(novato) == []


def test_salario_continua_aceito(novato):
    """Compatibilidade: quem informa a renda não perde o dado."""
    _concluir(novato, salary="5000.00", account_name="Conta", account_balance="100.00")

    rendas = novato["db"].exec(
        select(Income).where(Income.user_id == novato["user"].id)
    ).all()
    assert len(rendas) == 1
    assert rendas[0].amount == Decimal("5000.00")
