"""Saldo por conta: abertura, ajuste, transferência e extrato (ADR 0034).

O eixo do arquivo é a pergunta 17 do pedido — *"por que o saldo atual é exatamente
esse valor?"*. Toda resposta tem de sair do ledger, nunca de um número sobrescrito.

Os quatro eixos que não podem se misturar, e cada um tem teste aqui:

| Eixo        | Muda com                                   | NÃO muda com          |
|-------------|--------------------------------------------|-----------------------|
| Saldo       | abertura, ajuste, transferência, pagamento | compra no cartão      |
| Caixa       | pagamento, recebimento                     | ajuste, transferência |
| Competência | lançamento, renda                          | ajuste, transferência |
| Previsão    | obrigação em aberto, renda prevista        | o que já se moveu     |
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.jwt import create_access_token
from app.domain.dates import civil_instant, today_local
from app.main import app
from app.models.payment_account import PaymentAccount
from app.models.transaction import Transaction, TransactionPayer
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole

client = TestClient(app)

HOJE = today_local()
ONTEM = HOJE - timedelta(days=1)


@pytest.fixture(name="cena")
def cena_fixture(db_session: Session, override_get_session):
    user = User(name="Dona", email="saldo@t.com", password_hash="h", report_currency="BRL")
    db_session.add(user)
    ws = Workspace(name="Casa", base_currency="BRL")
    db_session.add(ws)
    db_session.flush()
    db_session.add(
        WorkspaceMembership(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.owner)
    )
    db_session.commit()
    db_session.refresh(user)
    token = create_access_token(data={"sub": str(user.id)})
    return {
        "db": db_session,
        "user_id": user.id,
        "ws_id": ws.id,
        "headers": {"Cookie": f"access_token={token}"},
    }


def _conta(cena, nome="Nubank", moeda="BRL"):
    r = client.post(
        "/api/v1/me/payment-accounts",
        json={"name": nome, "type": "checking", "currency": moeda},
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text
    return r.json()


def _abre(cena, conta_id, valor="1000.00", em=None):
    r = client.put(
        f"/api/v1/me/payment-accounts/{conta_id}/opening-balance",
        json={"amount": valor, "as_of": (em or ONTEM).isoformat()},
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text
    return r.json()


def _saldo(cena):
    r = client.get("/api/v1/me/balance", headers=cena["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def _da_conta(corpo, conta_id):
    return next(c for c in corpo["accounts"] if c["account_id"] == conta_id)


def _overview(cena):
    r = client.get("/api/v1/me/overview", headers=cena["headers"])
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# 1. Saldo inicial


def test_conta_sem_saldo_inicial_responde_none_e_nao_zero(cena):
    """Zero é um número errado apresentado com a confiança de um certo.

    A migração não inventa saldo (§6 do pedido), então a conta nasce sem abertura
    e a tela tem de PEDIR o número — não afirmar que a pessoa não tem dinheiro.
    """
    conta = _conta(cena)
    corpo = _saldo(cena)

    assert _da_conta(corpo, conta["id"])["balance"] is None
    assert corpo["total"] is None, "sem nenhuma conta configurada não há total"
    assert corpo["accounts_without_opening"] == 1
    assert corpo["projected_balance"] is None, (
        "projetar a partir de um saldo desconhecido daria um número inventado"
    )


def test_saldo_inicial_define_o_ponto_de_partida(cena):
    conta = _conta(cena)
    _abre(cena, conta["id"], "8350.42")

    corpo = _saldo(cena)
    linha = _da_conta(corpo, conta["id"])
    assert Decimal(linha["balance"]) == Decimal("8350.42")
    assert Decimal(linha["opening_amount"]) == Decimal("8350.42")
    assert linha["opening_on"] == ONTEM.isoformat()
    assert Decimal(corpo["total"]) == Decimal("8350.42")


def test_saldo_inicial_nao_e_renda_nem_resultado(cena):
    """"Isso não deve ser tratado como renda" (§6). O ponto do teste é que o
    número aparece no saldo e em MAIS NENHUM lugar."""
    conta = _conta(cena)
    _abre(cena, conta["id"], "8350.42")

    visao = _overview(cena)
    assert Decimal(visao["income"]) == Decimal("0.00")
    assert Decimal(visao["cash_in"]) == Decimal("0.00")
    assert Decimal(visao["result"]) == Decimal("0.00")


def test_movimento_anterior_a_abertura_nao_conta_mas_e_avisado(cena):
    """Certo, porque o saldo informado já o contém; mudo, seria um defeito.

    Quem lança em janeiro o extrato de dezembro precisa entender por que o número
    não se moveu — daí o contador separado.
    """
    conta = _conta(cena)
    _abre(cena, conta["id"], "1000.00", em=HOJE)

    antigo = civil_instant(HOJE - timedelta(days=30))
    tx = Transaction(
        title="Compra velha", total_amount=Decimal("100.00"), currency="BRL",
        transaction_date=antigo, settled_at=antigo, workspace_id=cena["ws_id"],
        created_by_user_id=cena["user_id"],
    )
    cena["db"].add(tx)
    cena["db"].flush()
    cena["db"].add(TransactionPayer(
        transaction_id=tx.id, user_id=cena["user_id"],
        amount=Decimal("100.00"), account_id=conta["id"],
    ))
    cena["db"].commit()

    corpo = _saldo(cena)
    assert Decimal(_da_conta(corpo, conta["id"])["balance"]) == Decimal("1000.00")
    assert corpo["movements_before_opening"] == 1, (
        "o movimento é ignorado, mas a tela precisa poder dizer por quê"
    )


def test_movimento_sem_conta_e_contado(cena):
    """Registrar a despesa sem dizer de onde saiu é legítimo — e o buraco no saldo
    que isso abre não pode ser silencioso."""
    conta = _conta(cena)
    _abre(cena, conta["id"], "1000.00", em=ONTEM)

    tx = Transaction(
        title="Padaria", total_amount=Decimal("30.00"), currency="BRL",
        transaction_date=civil_instant(HOJE), settled_at=civil_instant(HOJE),
        workspace_id=cena["ws_id"], created_by_user_id=cena["user_id"],
    )
    cena["db"].add(tx)
    cena["db"].flush()
    cena["db"].add(TransactionPayer(
        transaction_id=tx.id, user_id=cena["user_id"], amount=Decimal("30.00"),
    ))
    cena["db"].commit()

    corpo = _saldo(cena)
    assert Decimal(_da_conta(corpo, conta["id"])["balance"]) == Decimal("1000.00")
    assert corpo["unassigned_movements"] == 1


# ---------------------------------------------------------------------------
# 2. Ajuste / conciliação


def test_ajuste_positivo_muda_saldo_e_nao_muda_mais_nada(cena):
    """Sistema em 1.000, banco em 1.078,47 → movimento de +78,47.

    E o resto do app não se mexe: ajuste não é renda, não é despesa e não distorce
    o resultado do mês (§7).
    """
    conta = _conta(cena)
    _abre(cena, conta["id"], "1000.00")

    r = client.post(
        f"/api/v1/me/payment-accounts/{conta['id']}/adjustment",
        json={"real_balance": "1078.47", "note": "conferido no app do banco"},
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["amount"]) == Decimal("78.47")
    assert Decimal(r.json()["previous_balance"]) == Decimal("1000.00")
    assert Decimal(r.json()["new_balance"]) == Decimal("1078.47")

    assert Decimal(_da_conta(_saldo(cena), conta["id"])["balance"]) == Decimal("1078.47")

    visao = _overview(cena)
    assert Decimal(visao["income"]) == Decimal("0.00"), "ajuste NÃO é renda"
    assert Decimal(visao["consumption"]) == Decimal("0.00"), "ajuste NÃO é consumo"
    assert Decimal(visao["cash_in"]) == Decimal("0.00")
    assert Decimal(visao["cash_out"]) == Decimal("0.00")
    assert Decimal(visao["result"]) == Decimal("0.00")


def test_ajuste_negativo(cena):
    conta = _conta(cena)
    _abre(cena, conta["id"], "1000.00")

    r = client.post(
        f"/api/v1/me/payment-accounts/{conta['id']}/adjustment",
        json={"real_balance": "900.00"},
        headers=cena["headers"],
    )
    assert Decimal(r.json()["amount"]) == Decimal("-100.00")
    assert Decimal(_da_conta(_saldo(cena), conta["id"])["balance"]) == Decimal("900.00")


def test_ajuste_sem_diferenca_e_recusado(cena):
    conta = _conta(cena)
    _abre(cena, conta["id"], "1000.00")
    r = client.post(
        f"/api/v1/me/payment-accounts/{conta['id']}/adjustment",
        json={"real_balance": "1000.00"},
        headers=cena["headers"],
    )
    assert r.status_code == 422


def test_ajuste_sem_saldo_inicial_e_recusado(cena):
    """Sem ponto de partida não há diferença a calcular — e inventar um zero como
    base gravaria um ajuste do tamanho do saldo inteiro."""
    conta = _conta(cena)
    r = client.post(
        f"/api/v1/me/payment-accounts/{conta['id']}/adjustment",
        json={"real_balance": "900.00"},
        headers=cena["headers"],
    )
    assert r.status_code == 409


def test_ajuste_vira_linha_datada_e_nao_reescreve_o_passado(cena):
    """§29: o histórico precisa continuar explicável."""
    conta = _conta(cena)
    _abre(cena, conta["id"], "1000.00")
    client.post(
        f"/api/v1/me/payment-accounts/{conta['id']}/adjustment",
        json={"real_balance": "1078.47", "occurred_on": HOJE.isoformat()},
        headers=cena["headers"],
    )

    extrato = client.get(
        f"/api/v1/me/payment-accounts/{conta['id']}/statement", headers=cena["headers"]
    ).json()
    fontes = [e["source"] for e in extrato["entries"]]
    assert fontes == ["opening_balance", "adjustment"]
    assert Decimal(extrato["entries"][0]["running_balance"]) == Decimal("1000.00"), (
        "a abertura continua valendo o que valia — o ajuste não a reescreveu"
    )
    assert Decimal(extrato["entries"][-1]["running_balance"]) == Decimal("1078.47")


# ---------------------------------------------------------------------------
# 3. Transferência


def test_transferencia_move_sem_criar_nem_destruir_dinheiro(cena):
    origem = _conta(cena, "Nubank")
    destino = _conta(cena, "Itaú")
    _abre(cena, origem["id"], "5000.00")
    _abre(cena, destino["id"], "2000.00")

    antes = Decimal(_saldo(cena)["total"])
    r = client.post(
        "/api/v1/me/transfers",
        json={
            "from_account_id": origem["id"], "to_account_id": destino["id"],
            "from_amount": "1000.00",
        },
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text

    corpo = _saldo(cena)
    assert Decimal(_da_conta(corpo, origem["id"])["balance"]) == Decimal("4000.00")
    assert Decimal(_da_conta(corpo, destino["id"])["balance"]) == Decimal("3000.00")
    assert Decimal(corpo["total"]) == antes, "o total não pode se mexer"


def test_transferencia_nao_e_renda_nem_despesa(cena):
    origem = _conta(cena, "Nubank")
    destino = _conta(cena, "Itaú")
    _abre(cena, origem["id"], "5000.00")
    _abre(cena, destino["id"], "0.00")
    client.post(
        "/api/v1/me/transfers",
        json={
            "from_account_id": origem["id"], "to_account_id": destino["id"],
            "from_amount": "1000.00",
        },
        headers=cena["headers"],
    )

    visao = _overview(cena)
    assert Decimal(visao["cash_in"]) == Decimal("0.00"), (
        "transferência inflaria os dois lados e o net_cash acertaria por acidente"
    )
    assert Decimal(visao["cash_out"]) == Decimal("0.00")
    assert Decimal(visao["income"]) == Decimal("0.00")
    assert Decimal(visao["consumption"]) == Decimal("0.00")


def test_transferencia_para_a_mesma_conta_e_recusada(cena):
    conta = _conta(cena)
    r = client.post(
        "/api/v1/me/transfers",
        json={
            "from_account_id": conta["id"], "to_account_id": conta["id"],
            "from_amount": "10.00",
        },
        headers=cena["headers"],
    )
    assert r.status_code == 400


def test_transferencia_multimoeda_exige_os_dois_valores(cena):
    """Nada é convertido em silêncio (§27)."""
    origem = _conta(cena, "Nubank", "BRL")
    destino = _conta(cena, "Wise", "USD")

    r = client.post(
        "/api/v1/me/transfers",
        json={
            "from_account_id": origem["id"], "to_account_id": destino["id"],
            "from_amount": "5400.00",
        },
        headers=cena["headers"],
    )
    assert r.status_code == 400
    assert "quanto entrou" in r.json()["error"]["message"]

    r = client.post(
        "/api/v1/me/transfers",
        json={
            "from_account_id": origem["id"], "to_account_id": destino["id"],
            "from_amount": "5400.00", "to_amount": "1000.00",
        },
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["exchange_rate"]) == Decimal("0.185185")


def test_transferencia_excluida_leva_as_duas_pernas(cena):
    """Uma linha, duas pernas: meia transferência não é representável."""
    origem = _conta(cena, "Nubank")
    destino = _conta(cena, "Itaú")
    _abre(cena, origem["id"], "5000.00")
    _abre(cena, destino["id"], "0.00")
    t = client.post(
        "/api/v1/me/transfers",
        json={
            "from_account_id": origem["id"], "to_account_id": destino["id"],
            "from_amount": "1000.00",
        },
        headers=cena["headers"],
    ).json()

    client.delete(f"/api/v1/me/transfers/{t['id']}", headers=cena["headers"])
    corpo = _saldo(cena)
    assert Decimal(_da_conta(corpo, origem["id"])["balance"]) == Decimal("5000.00")
    assert Decimal(_da_conta(corpo, destino["id"])["balance"]) == Decimal("0.00")


# ---------------------------------------------------------------------------
# 4. Ciclo de vida da conta


def test_conta_com_saldo_nao_pode_ser_excluida(cena):
    """Antes do saldo, excluir era tirar da lista de origens. Agora seria fazer um
    dinheiro que existe desaparecer da tela sem movimento que explicasse."""
    conta = _conta(cena)
    _abre(cena, conta["id"], "1000.00")

    r = client.delete(f"/api/v1/me/payment-accounts/{conta['id']}", headers=cena["headers"])
    assert r.status_code == 409
    assert "saldo" in r.json()["error"]["message"].lower()


def test_conta_zerada_pode_ser_excluida(cena):
    conta = _conta(cena)
    _abre(cena, conta["id"], "0.00")
    r = client.delete(f"/api/v1/me/payment-accounts/{conta['id']}", headers=cena["headers"])
    assert r.status_code == 200


def test_reativar_conta_com_historico_preserva_a_moeda(cena):
    """A moeda é a unidade de conta do saldo: trocá-la reinterpretaria em USD o que
    foi somado em BRL, sem nenhuma linha no extrato que explicasse."""
    conta = _conta(cena, "Nubank", "BRL")
    _abre(cena, conta["id"], "0.00")
    client.delete(f"/api/v1/me/payment-accounts/{conta['id']}", headers=cena["headers"])

    r = client.post(
        "/api/v1/me/payment-accounts",
        json={"name": "Nubank", "type": "checking", "currency": "USD"},
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["currency"] == "BRL", "a conta tem histórico: a moeda não muda"


# ---------------------------------------------------------------------------
# 5. Segurança: conta é da pessoa (ADR 0021/§38)


def test_saldo_de_outra_pessoa_nao_vaza(cena, db_session):
    outro = User(name="Vizinho", email="vizinho@t.com", password_hash="h")
    db_session.add(outro)
    db_session.commit()
    db_session.refresh(outro)
    alheia = PaymentAccount(name="Secreta", currency="BRL", owner_user_id=outro.id)
    db_session.add(alheia)
    db_session.commit()
    db_session.refresh(alheia)

    for metodo, caminho, corpo in (
        ("get", f"/api/v1/me/payment-accounts/{alheia.id}/statement", None),
        ("put", f"/api/v1/me/payment-accounts/{alheia.id}/opening-balance",
         {"amount": "1.00", "as_of": HOJE.isoformat()}),
        ("post", f"/api/v1/me/payment-accounts/{alheia.id}/adjustment",
         {"real_balance": "1.00"}),
    ):
        r = getattr(client, metodo)(
            caminho, headers=cena["headers"], **({"json": corpo} if corpo else {})
        )
        assert r.status_code == 404, f"{caminho} vazou: {r.status_code}"

    assert _saldo(cena)["accounts"] == []


def test_extrato_sem_saldo_inicial_nao_afirma_zero(cena):
    """A mesma regra da tela de Contas, aplicada ao extrato.

    Uma coluna de saldo corrente que começa em "R$ 0,00" AFIRMA que a conta
    estava zerada — e ninguém disse isso. Os movimentos continuam listados, porque
    eles aconteceram; o que não se sabe é o saldo.
    """
    conta = _conta(cena)
    tx = Transaction(
        title="Padaria", total_amount=Decimal("30.00"), currency="BRL",
        transaction_date=civil_instant(HOJE), settled_at=civil_instant(HOJE),
        workspace_id=cena["ws_id"], created_by_user_id=cena["user_id"],
    )
    cena["db"].add(tx)
    cena["db"].flush()
    cena["db"].add(TransactionPayer(
        transaction_id=tx.id, user_id=cena["user_id"],
        amount=Decimal("30.00"), account_id=conta["id"],
    ))
    cena["db"].commit()

    extrato = client.get(
        f"/api/v1/me/payment-accounts/{conta['id']}/statement", headers=cena["headers"]
    ).json()

    assert extrato["balance"] is None
    assert len(extrato["entries"]) == 1, "o movimento aconteceu e continua listado"
    assert extrato["entries"][0]["running_balance"] is None, (
        "sem abertura, a coluna de saldo não pode inventar um ponto de partida"
    )
