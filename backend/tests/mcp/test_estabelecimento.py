"""Estabelecimento pelo agente (ADR 0038).

As tools de vocabulário (`categories_*`, `kind=merchant`) e as de lançamento
chamam o MESMO comando da tela (`commands/merchants.py`). Aqui se confere o
caminho da IA: o nome vira o estabelecimento certo, o parecido vira pergunta (e
não um segundo cadastro do mesmo lugar), e a busca e a soma usam o vínculo.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlmodel import select

from app.models.merchant import Merchant
from app.models.transaction import Transaction
from tests.mcp.conftest import call_tool, err, ok
from tests.mcp.scenario import monta


@pytest.fixture
def c(db_session, mcp_client):
    return monta(db_session, mcp_client)


def _cria(mcp_client, c, **extra):
    corpo = {"idempotency_key": str(uuid4()), "title": "Compra", "amount": "50.00", "space": "Casa", **extra}
    return ok(call_tool(mcp_client, c.token, "transactions_create", corpo))["transaction"]


def _estabelecimento(mcp_client, c, nome, **extra):
    return ok(call_tool(mcp_client, c.token, "categories_create", {"kind": "merchant", "name": nome, "space": "Casa", **extra}))


def test_cria_lista_e_recusa_o_repetido(mcp_client, db_session, c):
    m = _estabelecimento(mcp_client, c, "Uber", aliases=["UBER *TRIP"], default_category="Transporte")
    assert m["kind"] == "merchant"
    lista = ok(call_tool(mcp_client, c.token, "categories_list", {"space": "Casa"}))
    assert lista["merchants"] == [{"id": m["id"], "name": "Uber", "aliases": ["uber trip"], "default_category": "Transporte"}]
    dup = err(call_tool(mcp_client, c.token, "categories_create", {"kind": "merchant", "name": "uber", "space": "Casa"}))
    assert dup["code"] == "ALREADY_EXISTS" and dup["details"]["merchant_id"] == m["id"]
    # Cor é de categoria e tag; apelido é só do estabelecimento.
    assert err(call_tool(mcp_client, c.token, "categories_create", {"kind": "merchant", "name": "X", "space": "Casa", "color": "#000000"}))["code"] == "VALIDATION_ERROR"
    assert err(call_tool(mcp_client, c.token, "categories_create", {"name": "Y", "space": "Casa", "aliases": ["y"]}))["code"] == "VALIDATION_ERROR"


def test_o_lancamento_acha_pelo_apelido_pergunta_no_parecido_e_cria_o_novo(mcp_client, db_session, c):
    m = _estabelecimento(mcp_client, c, "McDonald's", aliases=["IFD*MC DONALDS"])
    assert _cria(mcp_client, c, merchant="ifd mc donalds")["merchant"] == {"id": m["id"], "name": "McDonald's"}
    # Sem `merchant`, o título que é um apelido vincula sozinho.
    assert _cria(mcp_client, c, title="IFD*MC DONALDS 0231")["merchant"]["id"] == m["id"]
    # Parecido não vincula nem cria: a pergunta é da pessoa.
    parecido = err(call_tool(mcp_client, c.token, "transactions_create", {
        "idempotency_key": str(uuid4()), "title": "Lanche", "amount": "30.00", "space": "Casa", "merchant": "Mc Donalds",
    }))
    assert parecido["code"] == "AMBIGUOUS" and parecido["candidates"][0]["name"] == "McDonald's"
    assert db_session.exec(select(Merchant).where(Merchant.workspace_id == c.casa.id)).all() == [db_session.get(Merchant, m["id"])]
    novo = _cria(mcp_client, c, merchant="Padaria Pão Quente")
    assert novo["merchant"]["name"] == "Padaria Pão Quente"


def test_editar_vincula_desvincula_e_diz_o_que_mudou(mcp_client, db_session, c):
    tx = _cria(mcp_client, c, title="Almoço")
    _estabelecimento(mcp_client, c, "Restaurante Sabor")
    r = ok(call_tool(mcp_client, c.token, "transactions_update", {"transaction_id": tx["id"], "merchant": "Restaurante Sabor"}))
    assert r["transaction"]["merchant"]["name"] == "Restaurante Sabor" and r["changed"] == ["merchant"]
    assert r["previous"]["merchant"] is None
    r = ok(call_tool(mcp_client, c.token, "transactions_update", {"transaction_id": tx["id"], "merchant": ""}))
    assert r["transaction"]["merchant"] is None and r["changed"] == ["merchant"]


def test_busca_e_soma_por_estabelecimento(mcp_client, db_session, c):
    _estabelecimento(mcp_client, c, "Mercado Lela", aliases=["MERCADO LELA LTDA"])
    _cria(mcp_client, c, title="Feira", amount="100.00", merchant="Mercado Lela")
    _cria(mcp_client, c, title="MERCADO LELA LTDA", amount="40.00")
    _cria(mcp_client, c, title="Farmácia", amount="25.00")
    achados = ok(call_tool(mcp_client, c.token, "transactions_search", {"merchant": "mercado lela"}))
    assert sorted(i["title"] for i in achados["items"]) == ["Feira", "MERCADO LELA LTDA"]
    assert {i["merchant"] for i in achados["items"]} == {"Mercado Lela"}
    soma = ok(call_tool(mcp_client, c.token, "reports_breakdown", {"group_by": "merchant", "basis": "total", "space": "Casa"}))
    assert [(g["name"], g["amount"], g["count"]) for g in soma["groups"]] == [
        ("Mercado Lela", "140.00", 2), ("Sem estabelecimento", "25.00", 1),
    ]
    assert err(call_tool(mcp_client, c.token, "transactions_search", {"merchant": "Inexistente"}))["code"] == "NOT_FOUND"


def test_mesclar_apelidos_categoria_padrao_e_excluir(mcp_client, db_session, c):
    fica = _estabelecimento(mcp_client, c, "McDonald's")
    sai = _estabelecimento(mcp_client, c, "MC DONALDS", aliases=["IFD MC"])
    tx = _cria(mcp_client, c, merchant="MC DONALDS")
    r = ok(call_tool(mcp_client, c.token, "categories_update", {"kind": "merchant", "space": "Casa", "name": "MC DONALDS", "merge_into": "McDonald's"}))
    assert r["id"] == fica["id"] and r["previous_name"] == "MC DONALDS"
    db_session.expire_all()
    assert db_session.get(Transaction, tx["id"]).merchant_id == fica["id"]
    assert db_session.get(Merchant, sai["id"]).deleted_at is not None

    ok(call_tool(mcp_client, c.token, "categories_create", {"name": "Lanche", "space": "Casa"}))
    ok(call_tool(mcp_client, c.token, "categories_update", {
        "kind": "merchant", "space": "Casa", "id": fica["id"], "aliases": ["MCDONALDS SHOPPING"], "default_category": "Lanche",
    }))
    lista = ok(call_tool(mcp_client, c.token, "categories_list", {"space": "Casa"}))["merchants"]
    assert lista == [{"id": fica["id"], "name": "McDonald's", "aliases": ["mcdonalds shopping"], "default_category": "Lanche"}]
    ok(call_tool(mcp_client, c.token, "categories_update", {"kind": "merchant", "space": "Casa", "id": fica["id"], "default_category": ""}))
    assert ok(call_tool(mcp_client, c.token, "categories_list", {"space": "Casa"}))["merchants"][0]["default_category"] is None

    ok(call_tool(mcp_client, c.token, "categories_update", {"kind": "merchant", "space": "Casa", "id": fica["id"], "delete": True}))
    db_session.expire_all()
    assert db_session.get(Transaction, tx["id"]).merchant_id is None
    # Mesclar é só com o que fica; não se mistura com outra mudança.
    assert err(call_tool(mcp_client, c.token, "categories_update", {
        "kind": "merchant", "space": "Casa", "name": "X", "merge_into": "Y", "new_name": "Z",
    }))["code"] == "VALIDATION_ERROR"


def test_o_de_outro_espaco_nao_serve(mcp_client, db_session, c):
    alheio = ok(call_tool(mcp_client, c.token_bob, "categories_create", {"kind": "merchant", "name": "Do Bob", "space": "Espaço do Bob"}))
    r = err(call_tool(mcp_client, c.token, "categories_update", {"kind": "merchant", "space": "Casa", "id": alheio["id"], "new_name": "Meu"}))
    assert r["code"] == "NOT_FOUND"
    # Pelo nome, o de outro espaço não é achado: vira um novo, deste espaço.
    tx = _cria(mcp_client, c, merchant="Do Bob")
    assert tx["merchant"]["id"] != alheio["id"]


def test_a_compra_parcelada_inteira_troca_de_estabelecimento(mcp_client, db_session, c):
    _estabelecimento(mcp_client, c, "Magazine")
    _estabelecimento(mcp_client, c, "Casas Bahia")
    tx = _cria(mcp_client, c, title="Geladeira", amount="300.00", card="Nubank", installments=3, merchant="Magazine")
    r = ok(call_tool(mcp_client, c.token, "transactions_update", {"transaction_id": tx["id"], "scope": "purchase", "merchant": "Casas Bahia"}))
    assert r["transaction"]["merchant"]["name"] == "Casas Bahia"
    db_session.expire_all()
    grupo = db_session.exec(select(Transaction).where(
        Transaction.installment_group_id == db_session.get(Transaction, tx["id"]).installment_group_id,
        Transaction.deleted_at.is_(None),
    )).all()
    assert len(grupo) == 3 and {t.merchant_id for t in grupo} == {r["transaction"]["merchant"]["id"]}
    # Mudar outra coisa da compra não apaga o estabelecimento.
    r = ok(call_tool(mcp_client, c.token, "transactions_update", {"transaction_id": r["transaction"]["id"], "scope": "purchase", "title": "Geladeira nova"}))
    assert r["transaction"]["merchant"]["name"] == "Casas Bahia"


def test_nome_exato_sem_chave_de_apelido_serve(mcp_client, db_session, c):
    m = _estabelecimento(mcp_client, c, "7-11")
    assert _cria(mcp_client, c, merchant="7-11")["merchant"]["id"] == m["id"]
