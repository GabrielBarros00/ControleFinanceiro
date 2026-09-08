"""Recorrência "no cartão" precisa de um cartão — como o lançamento avulso.

## Como isto apareceu

Numa varredura de telas com a base cheia, "Contas a pagar" listava uma despesa
etiquetada **"Cartão de crédito"**. O ADR 0029 exclui a compra no cartão desse
recorte de propósito: quem a paga é a FATURA, e cobrá-la de novo como conta
avulsa é cobrar duas vezes.

A causa não estava na tela. `validate_payment_method` (schemas/transaction.py)
recusa `payment_method='credit_card'` sem `credit_card_id` — mas essa validação
vive na rota de LANÇAMENTO. A rota de recorrência valida o caminho contrário
(cartão presente exige método `credit_card`) e não este, então aceitava o
template. Medido: avulso devolve 422, recorrência devolvia 200.

## Por que importa

A ocorrência materializada não passa pelo schema do lançamento — o
`RecurringService` monta o `Transaction` direto. O template inconsistente gera,
sozinho e todo mês, lançamentos num estado que a rota de criação proíbe:

- eles se dizem "no cartão", então a pessoa espera vê-los na fatura;
- não têm cartão, então não entram em fatura nenhuma;
- e caem em Contas a pagar, onde compra no cartão não deveria estar.

Um estado que nenhuma tela sabe representar e que só o tempo cria.
"""
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.jwt import create_access_token
from app.main import app
from app.models.credit_card import CreditCard
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole

client = TestClient(app)


@pytest.fixture(name="cena")
def cena_fixture(db_session: Session, override_get_session):
    dono = User(name="Dona", email="dona@rec-cartao.com", password_hash="h")
    ws = Workspace(name="Casa", base_currency="BRL")
    db_session.add_all([dono, ws])
    db_session.commit()
    db_session.add(WorkspaceMembership(
        workspace_id=ws.id, user_id=dono.id, role=WorkspaceRole.owner,
    ))
    from decimal import Decimal
    cartao = CreditCard(
        name="Nubank", limit=Decimal("5000.00"), closing_day=3, due_day=10,
        currency="BRL", owner_user_id=dono.id,
    )
    db_session.add(cartao)
    db_session.commit()
    db_session.refresh(cartao)
    return {
        "ws": ws, "dono": dono, "cartao": cartao,
        "h": {"Cookie": f"access_token={create_access_token({'sub': str(dono.id)})}"},
    }


def _criar(cena, **corpo):
    base = {
        "title": "Assinatura", "base_amount": "49.90",
        "frequency": "monthly", "day_of_month": 15,
    }
    return client.post(
        f"/api/v1/workspaces/{cena['ws'].id}/recurring",
        json={**base, **corpo}, headers=cena["h"],
    )


def test_credito_sem_cartao_e_recusado(cena):
    r = _criar(cena, payment_method="credit_card")

    assert r.status_code == 400, (
        "a recorrência aceitou 'no cartão' sem cartão — e vai gerar, todo mês, "
        f"lançamento que a rota de despesa recusa (veio {r.status_code})"
    )
    assert "cart" in r.text.lower(), f"a recusa não explica o que falta: {r.text}"


def test_a_mesma_recusa_vale_na_edicao(cena):
    """Senão o buraco só muda de porta: cria com pix, edita para crédito."""
    criada = _criar(cena, payment_method="pix")
    assert criada.status_code == 200, criada.text

    r = client.put(
        f"/api/v1/workspaces/{cena['ws'].id}/recurring/{criada.json()['id']}",
        json={"payment_method": "credit_card"}, headers=cena["h"],
    )

    assert r.status_code == 400, (
        f"a edição abriu o buraco que a criação fechou (veio {r.status_code})"
    )


# --------------------------------------------------------------------------- #
# CONTROLES — sem eles, "recusar tudo" passaria nos dois testes acima
# --------------------------------------------------------------------------- #

def test_controle_credito_com_cartao_continua_valendo(cena):
    r = _criar(
        cena, payment_method="credit_card", credit_card_id=cena["cartao"].id,
    )
    assert r.status_code == 200, r.text
    assert r.json()["credit_card_id"] == cena["cartao"].id


def test_controle_outro_metodo_nao_precisa_de_cartao(cena):
    assert _criar(cena, payment_method="pix").status_code == 200
    assert _criar(cena, payment_method="boleto").status_code == 200


def test_controle_sem_metodo_nenhum_continua_valendo(cena):
    """Recorrência sem forma de pagamento declarada é caso legítimo."""
    assert _criar(cena).status_code == 200
