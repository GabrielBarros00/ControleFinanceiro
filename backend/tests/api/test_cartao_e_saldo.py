"""Cartão de crédito NÃO é conta (§11 do pedido, ADR 0034).

    compra no cartão != saída de caixa
    pagamento da fatura = saída de caixa

A distinção já valia para o caixa desde o ADR 0022. O que esta onda acrescenta é o
SALDO, e com ele um jeito novo de errar: se a compra no cartão passasse a debitar a
conta bancária, o mesmo dinheiro sairia duas vezes — uma na compra, outra quando a
fatura fosse paga.

Também mora aqui a invariante de moeda (seção 0 do plano): a conta é a unidade de
conta do saldo, então declarar que USD 500 saíram de uma conta em reais soma moedas
diferentes em silêncio. Antes desta onda os três gates de conta (existe, é do dono,
está ativa) deixavam isso passar.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.jwt import create_access_token
from app.domain.dates import civil_instant, month_key, today_local
from app.main import app
from app.models.credit_card import CardStatement, CreditCard, StatementStatus
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole

client = TestClient(app)

HOJE = today_local()
ONTEM = HOJE - timedelta(days=1)


@pytest.fixture(name="cena")
def cena_fixture(db_session: Session, override_get_session):
    user = User(name="Dona", email="cartao_saldo@t.com", password_hash="h",
                report_currency="BRL")
    db_session.add(user)
    ws = Workspace(name="Casa", base_currency="BRL")
    db_session.add(ws)
    db_session.flush()
    db_session.add(
        WorkspaceMembership(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.owner)
    )
    card = CreditCard(
        name="Nubank", limit=Decimal("5000.00"), closing_day=25, due_day=5,
        currency="BRL", owner_user_id=user.id,
    )
    db_session.add(card)
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(card)
    token = create_access_token(data={"sub": str(user.id)})
    return {
        "db": db_session, "user_id": user.id, "ws_id": ws.id, "card_id": card.id,
        "headers": {"Cookie": f"access_token={token}"},
    }


def _conta(cena, nome="Itaú", moeda="BRL"):
    r = client.post(
        "/api/v1/me/payment-accounts",
        json={"name": nome, "type": "checking", "currency": moeda},
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text
    return r.json()


def _abre(cena, conta_id, valor="5000.00"):
    r = client.put(
        f"/api/v1/me/payment-accounts/{conta_id}/opening-balance",
        json={"amount": valor, "as_of": ONTEM.isoformat()},
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text


def _saldo_total(cena):
    r = client.get("/api/v1/me/balance", headers=cena["headers"])
    assert r.status_code == 200, r.text
    return Decimal(r.json()["total"])


def _fecha(cena, statement_id):
    """Fatura em aberto não se paga (ADR 0011) — fecha primeiro, como no app."""
    r = client.post(
        f"/api/v1/me/credit-cards/{cena['card_id']}/statements/{statement_id}/close",
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text


def _compra_no_cartao(cena, valor="300.00"):
    r = client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/",
        json={
            "title": "Compra", "total_amount": valor,
            "transaction_date": civil_instant(HOJE).isoformat(),
            "billing_month": month_key(HOJE),
            "payment_method": "credit_card",
            "credit_card_id": cena["card_id"],
            "payers": [{"user_id": cena["user_id"], "amount": valor,
                        "payment_method": "credit_card"}],
            "splits": [{"user_id": cena["user_id"], "split_method": "fixed",
                        "input_value": valor}],
        },
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------


def test_compra_no_cartao_nao_reduz_o_saldo_da_conta(cena):
    conta = _conta(cena)
    _abre(cena, conta["id"], "5000.00")

    _compra_no_cartao(cena, "300.00")

    assert _saldo_total(cena) == Decimal("5000.00"), (
        "a compra é obrigação, não saída — o dinheiro ainda está na conta"
    )


def test_pagamento_da_fatura_reduz_o_saldo_uma_vez_so(cena):
    conta = _conta(cena)
    _abre(cena, conta["id"], "5000.00")
    tx = _compra_no_cartao(cena, "300.00")

    fatura = cena["db"].get(CardStatement, tx["statement_id"])
    _fecha(cena, fatura.id)
    r = client.post(
        f"/api/v1/me/credit-cards/{cena['card_id']}/statements/{fatura.id}/pay",
        json={"amount": "300.00", "account_id": conta["id"]},
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text

    assert _saldo_total(cena) == Decimal("4700.00"), (
        "o evento de caixa é o pagamento da FATURA, e ele acontece uma vez"
    )


def test_pagamento_parcial_da_fatura_desconta_so_o_que_saiu(cena):
    conta = _conta(cena)
    _abre(cena, conta["id"], "5000.00")
    tx = _compra_no_cartao(cena, "300.00")
    fatura = cena["db"].get(CardStatement, tx["statement_id"])
    _fecha(cena, fatura.id)

    r = client.post(
        f"/api/v1/me/credit-cards/{cena['card_id']}/statements/{fatura.id}/pay",
        json={"amount": "100.00", "account_id": conta["id"]},
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text
    assert _saldo_total(cena) == Decimal("4900.00")


def test_fatura_em_aberto_entra_na_projecao_e_nao_no_saldo(cena):
    """§10: a fatura que vence no mês é saída futura conhecida — e a compra que a
    compõe NÃO entra separadamente, senão o mesmo dinheiro seria pedido duas vezes.
    """
    conta = _conta(cena)
    _abre(cena, conta["id"], "5000.00")
    _compra_no_cartao(cena, "300.00")

    corpo = client.get("/api/v1/me/balance", headers=cena["headers"]).json()
    assert Decimal(corpo["total"]) == Decimal("5000.00")

    tipos = {linha["kind"]: Decimal(linha["amount"]) for linha in corpo["breakdown"]}
    assert "payables" not in tipos, "compra no cartão não é conta a pagar"
    # A fatura do ciclo corrente ainda não venceu neste mês em todo cenário; o que
    # o teste garante é que, quando ela entra, entra UMA vez e pelo saldo dela.
    if "statements" in tipos:
        assert tipos["statements"] == Decimal("300.00")
        assert Decimal(corpo["payable_total"]) == Decimal("300.00")


# ---------------------------------------------------------------------------
# A invariante de moeda (seção 0 do plano)


def test_conta_em_outra_moeda_nao_pode_pagar_a_fatura(cena):
    conta = _conta(cena, "Wise", "USD")
    tx = _compra_no_cartao(cena, "300.00")
    fatura = cena["db"].get(CardStatement, tx["statement_id"])
    _fecha(cena, fatura.id)

    r = client.post(
        f"/api/v1/me/credit-cards/{cena['card_id']}/statements/{fatura.id}/pay",
        json={"amount": "300.00", "account_id": conta["id"]},
        headers=cena["headers"],
    )
    assert r.status_code == 400
    assert "USD" in r.json()["error"]["message"]


def test_conta_em_outra_moeda_nao_pode_ser_origem_de_lancamento(cena):
    conta = _conta(cena, "Wise", "USD")
    r = client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/",
        json={
            "title": "Mercado", "total_amount": "100.00",
            "transaction_date": civil_instant(HOJE).isoformat(),
            "billing_month": month_key(HOJE),
            "payers": [{"user_id": cena["user_id"], "amount": "100.00",
                        "account_id": conta["id"]}],
            "splits": [{"user_id": cena["user_id"], "split_method": "fixed",
                        "input_value": "100.00"}],
        },
        headers=cena["headers"],
    )
    assert r.status_code == 400
    assert "USD" in r.json()["error"]["message"]


def test_trocar_a_moeda_base_com_conta_atribuida_e_recusado(cena):
    """A troca reescreve `TransactionPayer.amount`, que alimenta o saldo PESSOAL.

    Sem esta barreira, um ato de workspace mudaria retroativamente o saldo bancário
    de cada membro — sem nenhuma linha nova no extrato que explicasse.
    """
    conta = _conta(cena, "Itaú", "BRL")
    r = client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/",
        json={
            "title": "Mercado", "total_amount": "100.00",
            "transaction_date": civil_instant(HOJE).isoformat(),
            "billing_month": month_key(HOJE),
            "payers": [{"user_id": cena["user_id"], "amount": "100.00",
                        "account_id": conta["id"]}],
            "splits": [{"user_id": cena["user_id"], "split_method": "fixed",
                        "input_value": "100.00"}],
        },
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text

    troca = client.put(
        f"/api/v1/workspaces/{cena['ws_id']}",
        json={"base_currency": "USD"},
        headers=cena["headers"],
    )
    assert troca.status_code == 409, troca.text
    assert "conta" in troca.json()["error"]["message"].lower()


# ---------------------------------------------------------------------------
# Virada de mês: o saldo é contínuo


def test_saldo_nao_reseta_na_virada_do_mes(cena):
    """§4: "Saldo em 31/08 23:59 = R$ 7.250" significa "saldo em 01/09 00:00 = R$
    7.250". Não há cópia nem geração na virada — o saldo simplesmente não tem mês.
    """
    conta = _conta(cena)
    _abre(cena, conta["id"], "7250.00")

    deste_mes = client.get("/api/v1/me/balance", headers=cena["headers"]).json()
    proximo = (HOJE.replace(day=1) + timedelta(days=32)).replace(day=1)
    do_proximo = client.get(
        f"/api/v1/me/balance?month={month_key(proximo)}", headers=cena["headers"]
    ).json()

    assert Decimal(deste_mes["total"]) == Decimal("7250.00")
    assert Decimal(do_proximo["total"]) == Decimal("7250.00"), (
        "o saldo é o mesmo — o que muda com o mês é a PROJEÇÃO, não o saldo"
    )


def test_fatura_que_vence_no_mes_entra_na_projecao_pelo_SALDO(cena):
    """§10: a fatura que vence no mês é saída futura conhecida — pelo que FALTA.

    O caso do teste acima só cobria a fatura do ciclo corrente, que vence no mês
    seguinte e por isso ficava fora. Aqui a fatura vence DENTRO do mês, e o que
    entra é `effective_total − pago`: uma fatura paga pela metade só tira do caixa
    o que resta.
    """
    conta = _conta(cena)
    _abre(cena, conta["id"], "5000.00")

    # Fatura do ciclo ANTERIOR, fechada e vencendo neste mês.
    ciclo = (HOJE.replace(day=1) - timedelta(days=1))
    fatura = CardStatement(
        card_id=cena["card_id"], month=month_key(ciclo),
        status=StatementStatus.closed,
        closing_date=civil_instant(ciclo),
        due_date=civil_instant(HOJE.replace(day=min(HOJE.day + 1, 28))),
        total_amount=Decimal("1500.00"),
        closed_at=civil_instant(ciclo),
    )
    cena["db"].add(fatura)
    cena["db"].commit()
    cena["db"].refresh(fatura)

    corpo = client.get("/api/v1/me/balance", headers=cena["headers"]).json()
    tipos = {linha["kind"]: Decimal(linha["amount"]) for linha in corpo["breakdown"]}
    assert tipos["statements"] == Decimal("1500.00")
    assert Decimal(corpo["payable_total"]) == Decimal("1500.00")
    assert Decimal(corpo["projected_balance"]) == Decimal("3500.00")

    # Pagamento parcial: só o que RESTA continua sendo saída futura.
    r = client.post(
        f"/api/v1/me/credit-cards/{cena['card_id']}/statements/{fatura.id}/pay",
        json={"amount": "500.00", "account_id": conta["id"]},
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text

    corpo = client.get("/api/v1/me/balance", headers=cena["headers"]).json()
    tipos = {linha["kind"]: Decimal(linha["amount"]) for linha in corpo["breakdown"]}
    assert tipos["statements"] == Decimal("1000.00"), "o saldo da fatura, não o total"
    # O saldo já caiu 500 (o pagamento é caixa) e ainda faltam 1.000.
    assert Decimal(corpo["total"]) == Decimal("4500.00")
    assert Decimal(corpo["projected_balance"]) == Decimal("3500.00")


def test_fatura_que_vence_no_mes_QUE_VEM_fica_fora_da_projecao(cena):
    """O teto é o fim do mês pedido: o que vence depois não pressiona este mês."""
    conta = _conta(cena)
    _abre(cena, conta["id"], "5000.00")

    proximo = (HOJE.replace(day=1) + timedelta(days=40)).replace(day=10)
    cena["db"].add(CardStatement(
        card_id=cena["card_id"], month=month_key(proximo),
        status=StatementStatus.closed,
        closing_date=civil_instant(HOJE),
        due_date=civil_instant(proximo),
        total_amount=Decimal("900.00"),
        closed_at=civil_instant(HOJE),
    ))
    cena["db"].commit()

    corpo = client.get("/api/v1/me/balance", headers=cena["headers"]).json()
    tipos = {linha["kind"] for linha in corpo["breakdown"]}
    assert "statements" not in tipos
    assert Decimal(corpo["payable_total"]) == Decimal("0.00")
