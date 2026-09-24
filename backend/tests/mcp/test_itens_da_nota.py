"""Itens da nota, ajustes e concorrência otimista pelas tools de lançamento.

O cenário de aceitação é o do relatório de lacunas do ChatGPT (§27): uma compra
de R$ 100 no cartão em 2x, com arroz só de uma pessoa, shampoo só da outra e
refrigerante dividido. O app já sabia fazer isso (`split_mode=item`); o MCP não
expunha. Aqui a regra continua sendo a do app (`compute_transaction_breakdown` e o
fatiamento de `_plan_installment_items`) — o teste só confere que a tradução
chega lá e que a leitura mostra a compra inteira com os itens uma vez só.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlmodel import select

from app.models.transaction import SplitMode, Transaction, TransactionItem
from tests.mcp.conftest import call_tool, err, ok
from tests.mcp.scenario import monta


@pytest.fixture
def c(db_session, mcp_client):
    return monta(db_session, mcp_client)


def _cria(mcp_client, c, **args) -> dict:
    return ok(call_tool(mcp_client, c.token, "transactions_create", {"idempotency_key": str(uuid4()), **args}))


def _pessoas(lista) -> dict:
    return {p["person"]["name"]: p["amount"] for p in lista}


def test_cenario_do_relatorio_compra_parcelada_com_itens(mcp_client, db_session, c):
    feito = _cria(
        mcp_client, c, title="Savegnago", space="Casa", card="Nubank", installments=2, date=str(c.hoje),
        items=[
            {"title": "Arroz", "amount": "30.00", "owner": "eu", "category": "Mercado"},
            {"title": "Shampoo", "amount": "20.00", "owner": "João"},
            {"title": "Refrigerante", "amount": "50.00", "split_with": ["João"]},
        ],
    )
    tx = feito["transaction"]
    assert tx["split_mode"] == "item"
    assert [p["amount"] for p in feito["installments"]] == ["50.00", "50.00"]

    compra = tx["purchase"]
    assert compra["amount"] == "100.00" and compra["installments"] == 2
    assert _pessoas(compra["split"]) == {"Alice Souza": "55.00", "João Pereira": "45.00"}
    assert compra["my_share"] == "55.00"
    # Os itens aparecem UMA vez, com o valor cheio (não R$ 15 duas vezes).
    itens = {i["title"]: i for i in compra["items"]}
    assert set(itens) == {"Arroz", "Shampoo", "Refrigerante"}
    assert (itens["Arroz"]["amount"], itens["Arroz"]["my_share"]) == ("30.00", "30.00")
    assert (itens["Shampoo"]["amount"], itens["Shampoo"]["my_share"]) == ("20.00", "0.00")
    assert _pessoas(itens["Refrigerante"]["shares"]) == {"Alice Souza": "25.00", "João Pereira": "25.00"}
    assert itens["Arroz"]["category"]["name"] == "Mercado"

    # No banco: cada parcela tem os 3 itens fatiados, somando a parcela.
    parcelas = db_session.exec(
        select(Transaction).where(Transaction.installment_group_id == tx["installment"]["group_id"])
    ).all()
    for p in parcelas:
        linhas = db_session.exec(select(TransactionItem).where(TransactionItem.transaction_id == p.id)).all()
        assert len(linhas) == 3 and sum(i.amount for i in linhas) == p.total_amount


def test_itens_com_desconto_e_total_omitido(mcp_client, c):
    feito = _cria(
        mcp_client, c, title="Farmácia",
        items=[{"title": "Remédio", "amount": "40.00"}, {"title": "Protetor", "quantity": "2", "unit_amount": "10.00"}],
        adjustments=[{"type": "discount", "amount": "5.00", "description": "cupom"}],
    )["transaction"]
    assert feito["amount"] == "55.00" and feito["my_share"] == "55.00"
    assert [(i["title"], i["quantity"], i["amount"]) for i in feito["items"]] == [
        ("Remédio", "1", "40.00"), ("Protetor", "2", "20.00"),
    ]
    assert feito["adjustments"] == [{"type": "discount", "amount": "-5.00", "description": "cupom"}]


def test_itens_que_nao_fecham_o_total_explicam_a_diferenca(mcp_client, c):
    erro = err(call_tool(mcp_client, c.token, "transactions_create", {
        "idempotency_key": str(uuid4()), "title": "Mercado", "amount": "100.00",
        "items": [{"title": "Arroz", "amount": "60.00"}, {"title": "Feijão", "amount": "30.00"}],
    }))
    assert erro["code"] == "VALIDATION_ERROR" and "desconto, frete ou taxa" in erro["message"]
    assert erro["details"] == {"items_total": "90.00", "adjustments_total": "0.00", "amount": "100.00"}


def test_quantidade_que_nao_fecha_em_centavos_pede_o_total_da_linha(mcp_client, c):
    erro = err(call_tool(mcp_client, c.token, "transactions_create", {
        "idempotency_key": str(uuid4()), "title": "Feira",
        "items": [{"title": "Tomate", "quantity": "1.333", "unit_amount": "10.01"}],
    }))
    assert erro["code"] == "VALIDATION_ERROR" and "não fecha em centavos" in erro["message"]


def test_parcelado_com_ajuste_e_recusado_em_vez_de_perder_o_desconto(mcp_client, c):
    erro = err(call_tool(mcp_client, c.token, "transactions_create", {
        "idempotency_key": str(uuid4()), "title": "Loja", "card": "Nubank", "installments": 3,
        "items": [{"title": "Fone", "amount": "300.00"}],
        "adjustments": [{"type": "discount", "amount": "30.00"}],
    }))
    assert erro["code"] == "BUSINESS_RULE_VIOLATION" and "não parcela compra com ajustes" in erro["message"]


def test_parcelado_com_itens_sem_divisao_propria_nao_perde_itens(mcp_client, c):
    """No modo "divisão pela despesa" o parcelamento do app guarda UM item por parcela."""
    tx = _cria(
        mcp_client, c, title="Eletro", card="Nubank", installments=2,
        items=[{"title": "Liquidificador", "amount": "120.00"}, {"title": "Torradeira", "amount": "80.00"}],
    )["transaction"]
    assert tx["split_mode"] == "item"
    assert {i["title"] for i in tx["purchase"]["items"]} == {"Liquidificador", "Torradeira"}


def test_item_sem_divisao_quando_outra_pessoa_pagou(mcp_client, c):
    erro = err(call_tool(mcp_client, c.token, "transactions_create", {
        "idempotency_key": str(uuid4()), "title": "Mercado", "space": "Casa", "paid_by": "João",
        "items": [{"title": "Arroz", "amount": "30.00", "owner": "eu"}, {"title": "Pão", "amount": "10.00"}],
    }))
    assert erro["code"] == "VALIDATION_ERROR" and "split_with" in erro["message"]


def test_divisao_fixa_do_total_nao_se_distribui_por_item(mcp_client, c):
    erro = err(call_tool(mcp_client, c.token, "transactions_create", {
        "idempotency_key": str(uuid4()), "title": "Mercado", "space": "Casa", "card": "Nubank", "installments": 2,
        "split": [{"person": "eu", "amount": "70.00"}, {"person": "João", "amount": "30.00"}],
        "items": [{"title": "Arroz", "amount": "60.00"}, {"title": "Pão", "amount": "40.00"}],
    }))
    assert erro["code"] == "VALIDATION_ERROR" and "valores fixos" in erro["message"]


def test_editar_itens_troca_a_nota_inteira_e_mostra_o_antes(mcp_client, db_session, c):
    tx = _cria(mcp_client, c, title="Mercado", space="Casa", split_with=["João"],
               items=[{"title": "Arroz", "amount": "30.00"}, {"title": "Pão", "amount": "10.00"}])["transaction"]
    assert tx["split_mode"] == "transaction" and _pessoas(tx["split"]) == {"Alice Souza": "20.00", "João Pereira": "20.00"}
    feito = ok(call_tool(mcp_client, c.token, "transactions_update", {
        "transaction_id": tx["id"],
        "items": [
            {"title": "Arroz", "amount": "30.00", "owner": "eu"},
            {"title": "Pão", "amount": "12.00"},
            {"title": "Café", "amount": "18.00", "owner": "João"},
        ],
    }))
    depois = feito["transaction"]
    assert depois["amount"] == "60.00" and depois["split_mode"] == "item"
    # Pão sem divisão própria segue a do lançamento (metade/metade).
    assert _pessoas(depois["split"]) == {"Alice Souza": "36.00", "João Pereira": "24.00"}
    assert {"items", "amount", "split", "split_mode"} <= set(feito["changed"])
    assert [i["title"] for i in feito["previous"]["items"]] == ["Arroz", "Pão"]
    linhas = db_session.exec(select(TransactionItem).where(TransactionItem.transaction_id == tx["id"])).all()
    assert sorted(i.title for i in linhas) == ["Arroz", "Café", "Pão"]


def test_itens_de_parcelado_se_editam_na_compra_inteira(mcp_client, c):
    tx = _cria(mcp_client, c, title="TV", card="Nubank", installments=2,
               items=[{"title": "TV", "amount": "2000.00"}, {"title": "Suporte", "amount": "200.00"}])["transaction"]
    erro = err(call_tool(mcp_client, c.token, "transactions_update", {
        "transaction_id": tx["id"], "items": [{"title": "TV", "amount": "2200.00"}],
    }))
    assert erro["code"] == "VALIDATION_ERROR" and "scope=purchase" in erro["message"]
    feito = ok(call_tool(mcp_client, c.token, "transactions_update", {
        "transaction_id": tx["id"], "scope": "purchase",
        "items": [{"title": "TV", "amount": "1900.00"}, {"title": "Suporte", "amount": "150.00"}, {"title": "Cabo", "amount": "50.00"}],
    }))
    compra = feito["transaction"]["purchase"]
    assert compra["amount"] == "2100.00"
    assert {i["title"]: i["amount"] for i in compra["items"]} == {"TV": "1900.00", "Suporte": "150.00", "Cabo": "50.00"}


def test_versao_detecta_edicao_concorrente(mcp_client, c):
    tx = _cria(mcp_client, c, title="Padaria", amount="12.00")["transaction"]
    lida = tx["version"]
    assert len(lida) == 16
    ok(call_tool(mcp_client, c.token, "transactions_update", {"transaction_id": tx["id"], "title": "Padaria Pão Quente", "expected_version": lida}))
    # Outra edição com a versão VELHA não sobrescreve a mudança.
    erro = err(call_tool(mcp_client, c.token, "transactions_update", {"transaction_id": tx["id"], "amount": "15.00", "expected_version": lida}))
    assert erro["code"] == "CONFLICT" and erro["details"]["expected_version"] == lida
    atual = erro["details"]["current_version"]
    assert atual != lida
    erro = err(call_tool(mcp_client, c.token, "transactions_delete", {"transaction_id": tx["id"], "expected_version": lida}))
    assert erro["code"] == "CONFLICT"
    ok(call_tool(mcp_client, c.token, "transactions_delete", {"transaction_id": tx["id"], "expected_version": atual}))


def test_versao_muda_quando_so_as_tags_mudam(mcp_client, db_session, c):
    """`updated_at` não veria: tag é linha filha. A versão é o estado."""
    from app.models.tag import Tag

    db_session.add(Tag(workspace_id=c.pessoal.id, name="viagem"))
    db_session.commit()
    tx = _cria(mcp_client, c, title="Hotel", amount="300.00")["transaction"]
    depois = ok(call_tool(mcp_client, c.token, "transactions_update", {"transaction_id": tx["id"], "tags": ["viagem"]}))["transaction"]
    assert depois["version"] != tx["version"]
    mesma = ok(call_tool(mcp_client, c.token, "transactions_get", {"transaction_id": tx["id"]}))["transaction"]
    assert mesma["version"] == depois["version"]


def test_lancamento_simples_nao_repete_o_item_sombra(mcp_client, c):
    tx = _cria(mcp_client, c, title="Uber", amount="23.50", category="Transporte")["transaction"]
    assert tx["items"] == [] and tx["category"]["name"] == "Transporte" and tx["split_mode"] == "transaction"
    assert Decimal(tx["my_share"]) == Decimal("23.50")


def test_modo_por_item_no_banco(mcp_client, db_session, c):
    tx = _cria(mcp_client, c, title="Mercado", space="Casa",
               items=[{"title": "Arroz", "amount": "30.00", "owner": "João"}])["transaction"]
    assert db_session.get(Transaction, tx["id"]).split_mode == SplitMode.item
    assert tx["my_share"] == "0.00"
