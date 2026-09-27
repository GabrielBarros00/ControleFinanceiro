"""Edição parcial que mexe no dinheiro (auditoria 2026-09-26, A2).

O `PUT` sem `payers` gravava a moeda sem converter, lia o valor na moeda-base e
mantinha a cotação velha ao mudar a data. A tela e o MCP o evitavam, cada um com
a sua montagem da edição completa. Agora o comando completa a edição com a
divisão gravada e a passa pela mesma conversão e pelo mesmo cálculo da edição
completa. Estes testes fixam a regra na API; o lado do MCP está em
`tests/mcp/test_tools_write.py`.
"""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.models.category import Category
from app.models.credit_card import CreditCard
from app.models.payment_account import PaymentAccount
from app.models.transaction import TransactionPayer
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.services.currency_service import CurrencyService

client = TestClient(app)
DIA = "2026-06-10T12:00:00"


@pytest.fixture(name="casa")
def casa_fixture(db_session: Session, setup_data, override_get_session, monkeypatch):
    monkeypatch.setattr(CurrencyService, "get_rate_sync", lambda *a, **k: (Decimal("5.00"), "ptax"))
    ws, u1, u2 = setup_data["ws1"], setup_data["u1"], setup_data["u2"]
    db_session.add(WorkspaceMembership(workspace_id=ws.id, user_id=u2.id, role=WorkspaceRole.member))
    cartao = CreditCard(name="Nubank", limit=Decimal("5000"), closing_day=25, due_day=5, owner_user_id=u1.id)
    conta = PaymentAccount(name="Itaú", type="checking", owner_user_id=u1.id)
    alheia = PaymentAccount(name="Do u2", type="checking", owner_user_id=u2.id)
    categoria = Category(name="Mercado", workspace_id=ws.id)
    db_session.add_all([cartao, conta, alheia, categoria])
    db_session.commit()
    for obj in (cartao, conta, alheia, categoria):
        db_session.refresh(obj)
    return {
        "ws": ws.id, "u1": u1.id, "u2": u2.id, "h": setup_data["headers1"], "db": db_session,
        "cartao": cartao.id, "conta": conta, "alheia": alheia.id, "categoria": categoria.id,
    }


def _cria(casa, **extra) -> dict:
    corpo = {
        "title": "Mercado", "total_amount": "100.00", "transaction_date": DIA, "payment_method": "pix",
        "payers": [{"user_id": casa["u1"], "amount": "100.00"}],
        "splits": [{"user_id": casa["u1"], "split_method": "equal", "input_value": "0"}],
    }
    corpo.update(extra)
    r = client.post(f"/api/v1/workspaces/{casa['ws']}/transactions/", json=corpo, headers=casa["h"])
    assert r.status_code == 200, r.text
    return r.json()


def _edita(casa, tx_id: int, corpo: dict):
    return client.put(f"/api/v1/workspaces/{casa['ws']}/transactions/{tx_id}", json=corpo, headers=casa["h"])


def _dois_iguais(casa) -> list:
    return [{"user_id": u, "split_method": "equal", "input_value": "0"} for u in (casa["u1"], casa["u2"])]


# --- Total novo: reparte quando há um jeito só; senão pergunta -----------------

@pytest.mark.parametrize("estrutura, trecho", [
    ({"payers": "dois", "splits": "iguais"}, "informe quanto cada uma pagou"),
    ({"payers": "um", "splits": "fixos"}, "refaça a divisão"),
    ({"payers": "um", "splits": "iguais", "items": "dois"}, "editando os itens"),
])
def test_total_novo_que_nao_se_reparte_sozinho_e_recusado(casa, estrutura, trecho):
    pagadores = {
        "um": [{"user_id": casa["u1"], "amount": "100.00"}],
        "dois": [{"user_id": casa["u1"], "amount": "60.00"}, {"user_id": casa["u2"], "amount": "40.00"}],
    }[estrutura["payers"]]
    partes = {
        "iguais": _dois_iguais(casa),
        "fixos": [
            {"user_id": casa["u1"], "split_method": "fixed", "input_value": "70.00"},
            {"user_id": casa["u2"], "split_method": "fixed", "input_value": "30.00"},
        ],
    }[estrutura["splits"]]
    extra = {"payers": pagadores, "splits": partes}
    if estrutura.get("items"):
        extra["items"] = [{"title": "Arroz", "amount": "60.00"}, {"title": "Feijão", "amount": "40.00", "position": 1}]
    tx = _cria(casa, **extra)

    r = _edita(casa, tx["id"], {"total_amount": "120.00"})
    assert r.status_code == 400, r.text
    assert trecho in r.json()["error"]["message"]
    atual = client.get(f"/api/v1/workspaces/{casa['ws']}/transactions/{tx['id']}", headers=casa["h"]).json()
    assert atual["total_amount"] == "100.00"


def test_total_novo_com_um_item_leva_a_categoria_junto(casa):
    tx = _cria(casa, items=[{"title": "Mercado", "amount": "100.00", "category_id": casa["categoria"]}])
    r = _edita(casa, tx["id"], {"total_amount": "150.00"})
    assert r.status_code == 200, r.text
    [item] = r.json()["items"]
    assert (item["amount"], item["category_id"]) == ("150.00", casa["categoria"])


def test_total_novo_e_categoria_nova_na_mesma_edicao(casa):
    tx = _cria(casa, splits=_dois_iguais(casa))
    r = _edita(casa, tx["id"], {"total_amount": "150.00", "category_id": casa["categoria"]})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert [(i["amount"], i["category_id"]) for i in corpo["items"]] == [("150.00", casa["categoria"])]
    assert sorted(s["computed_amount"] for s in corpo["splits"]) == ["75.00", "75.00"]


# --- Reconversão: mesma compra, cotação nova, mesma proporção ------------------

def test_data_nova_reconverte_a_divisao_fixa_na_mesma_proporcao(casa, monkeypatch):
    """US$ 30 do u1 e US$ 20 do u2 continuam sendo isso com a cotação de outro dia.

    O MCP recusava ("informe a divisão de novo"): os valores fixos gravados estão
    na moeda-base, e ele não tinha como refazê-los. A proporção basta.
    """
    tx = _cria(
        casa, currency="USD", total_amount="50.00",
        payers=[{"user_id": casa["u1"], "amount": "50.00"}],
        splits=[
            {"user_id": casa["u1"], "split_method": "fixed", "input_value": "30.00"},
            {"user_id": casa["u2"], "split_method": "fixed", "input_value": "20.00"},
        ],
    )
    assert tx["total_amount"] == "250.00"
    monkeypatch.setattr(CurrencyService, "get_rate_sync", lambda *a, **k: (Decimal("6.00"), "ptax"))

    r = _edita(casa, tx["id"], {"transaction_date": "2026-06-01T12:00:00"})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert (corpo["total_amount"], corpo["original_amount"], corpo["original_currency"]) == ("300.00", "50.00", "USD")
    assert Decimal(corpo["exchange_rate"]) == Decimal("6.00")
    partes = {s["user_id"]: (s["input_value"], s["computed_amount"]) for s in corpo["splits"]}
    assert partes == {casa["u1"]: ("180.00", "180.00"), casa["u2"]: ("120.00", "120.00")}


def test_so_o_titulo_nao_refaz_a_divisao(casa):
    tx = _cria(casa, currency="USD", total_amount="50.00", payers=[{"user_id": casa["u1"], "amount": "50.00"}])
    antes = casa["db"].exec(select(TransactionPayer.id).where(TransactionPayer.transaction_id == tx["id"])).all()
    r = _edita(casa, tx["id"], {"title": "Mercado (EUA)"})
    assert r.status_code == 200, r.text
    assert r.json()["total_amount"] == "250.00"
    depois = casa["db"].exec(select(TransactionPayer.id).where(TransactionPayer.transaction_id == tx["id"])).all()
    assert depois == antes


def test_reenviar_valor_e_moeda_da_compra_nao_muda_nada(casa):
    """Formulário que reenvia tudo: "USD 50" igual ao da compra não vira coluna."""
    tx = _cria(casa, currency="USD", total_amount="50.00", payers=[{"user_id": casa["u1"], "amount": "50.00"}])
    r = _edita(casa, tx["id"], {"total_amount": "50.00", "currency": "USD", "title": "Mercado (EUA)"})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert (corpo["title"], corpo["total_amount"], corpo["currency"]) == ("Mercado (EUA)", "250.00", "BRL")
    assert (corpo["original_amount"], corpo["original_currency"]) == ("50.00", "USD")


def test_edicao_completa_sem_moeda_le_na_moeda_da_compra(casa):
    """Sem `currency`, a edição completa também está na moeda da compra.

    O padrão era a moeda-base gravada: pagadores de "60" numa compra de US$ 50
    viravam R$ 60, e o original sumia.
    """
    tx = _cria(casa, currency="USD", total_amount="50.00", payers=[{"user_id": casa["u1"], "amount": "50.00"}])
    r = _edita(casa, tx["id"], {
        "total_amount": "60.00",
        "payers": [{"user_id": casa["u1"], "amount": "60.00"}],
        "splits": [{"user_id": casa["u1"], "split_method": "equal", "input_value": "0"}],
    })
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert (corpo["total_amount"], corpo["original_amount"], corpo["original_currency"]) == ("300.00", "60.00", "USD")


# --- A origem do pagador segue a do lançamento --------------------------------

def test_ir_para_o_cartao_tira_a_conta_do_pagador(casa):
    tx = _cria(casa, payers=[{"user_id": casa["u1"], "amount": "100.00", "account_id": casa["conta"].id}])
    r = _edita(casa, tx["id"], {"credit_card_id": casa["cartao"], "payment_method": "credit_card"})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["payment_method"] == "credit_card" and corpo["statement_id"] is not None
    assert [(p["payment_method"], p["account_id"]) for p in corpo["payers"]] == [(None, None)]


def test_sair_do_cartao_tira_o_cartao_do_pagador(casa):
    """O pagador guardava `credit_card` numa compra sem cartão, e a edição seguinte dava 400."""
    tx = _cria(
        casa, credit_card_id=casa["cartao"], payment_method="credit_card",
        payers=[{"user_id": casa["u1"], "amount": "100.00", "payment_method": "credit_card"}],
    )
    r = _edita(casa, tx["id"], {"credit_card_id": None, "payment_method": "pix"})
    assert r.status_code == 200, r.text
    assert [p["payment_method"] for p in r.json()["payers"]] == [None]
    assert _edita(casa, tx["id"], {"title": "Mercado do mês"}).status_code == 200


def test_sair_do_cartao_com_dois_pagadores_pede_a_origem_de_cada_um(casa):
    """Com duas pessoas, o comando não decide de onde saiu o dinheiro de cada uma."""
    tx = _cria(
        casa, credit_card_id=casa["cartao"], payment_method="credit_card",
        payers=[
            {"user_id": casa["u1"], "amount": "60.00", "payment_method": "credit_card"},
            {"user_id": casa["u2"], "amount": "40.00", "payment_method": "pix"},
        ],
        splits=_dois_iguais(casa),
    )
    r = _edita(casa, tx["id"], {"credit_card_id": None, "payment_method": "pix"})
    assert r.status_code == 400, r.text
    assert "credit_card" in r.json()["error"]["message"]


# --- Conta da despesa de um pagador só ------------------------------------------

def test_conta_pela_edicao_parcial(casa):
    tx = _cria(casa)
    r = _edita(casa, tx["id"], {"account_id": casa["conta"].id})
    assert r.status_code == 200, r.text
    assert [p["account_id"] for p in r.json()["payers"]] == [casa["conta"].id]
    r = _edita(casa, tx["id"], {"account_id": None})
    assert r.status_code == 200, r.text
    assert [p["account_id"] for p in r.json()["payers"]] == [None]


@pytest.mark.parametrize("caso, trecho", [
    ("alheia", "não pertence a quem pagou"),
    ("cartao", "não sai de uma conta"),
    ("dois_pagadores", "a conta de cada uma vai na divisão"),
])
def test_conta_pela_edicao_parcial_recusada(casa, caso, trecho):
    extra, conta = {}, casa["conta"].id
    if caso == "alheia":
        conta = casa["alheia"]
    elif caso == "cartao":
        extra = {"credit_card_id": casa["cartao"], "payment_method": "credit_card"}
    else:
        extra = {
            "payers": [{"user_id": casa["u1"], "amount": "60.00"}, {"user_id": casa["u2"], "amount": "40.00"}],
            "splits": _dois_iguais(casa),
        }
    tx = _cria(casa, **extra)
    r = _edita(casa, tx["id"], {"account_id": conta})
    assert r.status_code == 400, r.text
    assert trecho in r.json()["error"]["message"]


def test_conta_junto_com_payers_e_recusada(casa):
    tx = _cria(casa)
    r = _edita(casa, tx["id"], {
        "account_id": casa["conta"].id,
        "payers": [{"user_id": casa["u1"], "amount": "100.00"}],
        "splits": [{"user_id": casa["u1"], "split_method": "equal", "input_value": "0"}],
    })
    assert r.status_code == 422, r.text
    assert "account_id OU payers" in r.json()["error"]["message"]


# --- O que mudou DEPOIS do lançamento não trava a correção de um valor ----------

def test_corrigir_o_valor_depois_de_desativar_a_conta(casa):
    """A conta foi desativada depois; a despesa antiga continua corrigível."""
    tx = _cria(casa, payers=[{"user_id": casa["u1"], "amount": "100.00", "account_id": casa["conta"].id}])
    casa["conta"].active = False
    casa["db"].add(casa["conta"])
    casa["db"].commit()

    r = _edita(casa, tx["id"], {"total_amount": "120.00"})
    assert r.status_code == 200, r.text
    assert [(p["amount"], p["account_id"]) for p in r.json()["payers"]] == [("120.00", casa["conta"].id)]


def test_corrigir_o_valor_depois_que_alguem_saiu_do_espaco(casa):
    tx = _cria(casa, splits=_dois_iguais(casa))
    vinculo = casa["db"].exec(select(WorkspaceMembership).where(
        WorkspaceMembership.workspace_id == casa["ws"], WorkspaceMembership.user_id == casa["u2"],
    )).one()
    casa["db"].delete(vinculo)
    casa["db"].commit()

    r = _edita(casa, tx["id"], {"total_amount": "120.00"})
    assert r.status_code == 200, r.text
    assert sorted(s["computed_amount"] for s in r.json()["splits"]) == ["60.00", "60.00"]


# --- `null` numa coluna obrigatória -----------------------------------------------

def test_null_explicito_em_coluna_obrigatoria_nao_mexe(casa):
    """Era 500: o `null` chegava ao `setattr` e o banco recusava no commit."""
    tx = _cria(casa)
    r = _edita(casa, tx["id"], {"total_amount": None, "title": None, "currency": None, "description": "nota"})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert (corpo["title"], corpo["total_amount"], corpo["description"]) == ("Mercado", "100.00", "nota")
