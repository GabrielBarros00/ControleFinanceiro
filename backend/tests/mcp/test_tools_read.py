"""Tools de leitura: descoberta, busca, fatura, relatórios, dívidas, contas a pagar."""
from datetime import timedelta
from decimal import Decimal

import pytest

from tests.mcp.conftest import call_tool, err, ok
from tests.mcp.scenario import categoria, cria_despesa, monta, ontem


@pytest.fixture
def c(db_session, mcp_client):
    return monta(db_session, mcp_client)


def test_spaces_list(mcp_client, c):
    espacos = ok(call_tool(mcp_client, c.token, "spaces_list"))["spaces"]
    nomes = {e["name"]: e for e in espacos}
    assert set(nomes) == {"Meu espaço", "Casa"}
    assert nomes["Meu espaço"]["personal"] is True
    assert nomes["Casa"]["members"] == 2 and nomes["Casa"]["my_role"] == "owner"


def test_people_list_filtra_por_nome_e_sem_acento(mcp_client, c):
    pessoas = ok(call_tool(mcp_client, c.token, "people_list", {"query": "joao"}))["people"]
    assert [p["name"] for p in pessoas] == ["João Pereira"]
    assert pessoas[0]["spaces"][0]["name"] == "Casa"


def test_people_list_nao_mostra_quem_nao_divide_espaco(mcp_client, c):
    pessoas = ok(call_tool(mcp_client, c.token, "people_list"))["people"]
    assert "Bob Lima" not in {p["name"] for p in pessoas}


def test_categories_list_exige_espaco_quando_ha_varios(mcp_client, c):
    erro = err(call_tool(mcp_client, c.token, "categories_list"))
    assert erro["code"] == "AMBIGUOUS"
    assert {x["name"] for x in erro["candidates"]} == {"Meu espaço", "Casa"}
    cats = ok(call_tool(mcp_client, c.token, "categories_list", {"space": "casa"}))
    assert "Alimentação" in {x["name"] for x in cats["categories"]}


def test_cards_list(mcp_client, c):
    cartoes = ok(call_tool(mcp_client, c.token, "cards_list"))["cards"]
    assert cartoes[0]["name"] == "Nubank"
    assert cartoes[0]["available_limit"] == "5000.00"
    assert cartoes[0]["current_statement"]["exists"] is False


def test_accounts_list(mcp_client, c):
    saida = ok(call_tool(mcp_client, c.token, "accounts_list"))
    assert saida["accounts"][0]["name"] == "Itaú"


def test_busca_por_texto_e_data_de_ontem(mcp_client, c):
    cria_despesa(mcp_client, c.alice, c.pessoal, title="McDonald's", amount="42.90", day=ontem(c))
    cria_despesa(mcp_client, c.alice, c.pessoal, title="McDonald's", amount="30.00", day=ontem(c) - timedelta(days=5))
    cria_despesa(mcp_client, c.alice, c.pessoal, title="Padaria", amount="12.00", day=ontem(c))
    achados = ok(call_tool(mcp_client, c.token, "transactions_search", {
        "text": "mcdonald", "date_from": ontem(c).isoformat(), "date_to": ontem(c).isoformat(),
    }))
    assert achados["total_count"] == 1
    assert achados["items"][0]["amount"] == "42.90"
    assert achados["totals"] == [{"currency": "BRL", "amount": "42.90", "count": 1}]


def test_busca_por_cartao_e_minha_parte(mcp_client, c):
    cria_despesa(mcp_client, c.alice, c.casa, title="Mercado", amount="100.00", day=c.hoje, card=c.nubank, split_with=[c.joao])
    cria_despesa(mcp_client, c.alice, c.pessoal, title="Cinema", amount="50.00", day=c.hoje)
    saida = ok(call_tool(mcp_client, c.token, "transactions_search", {"card": "nubank"}))
    assert saida["total_count"] == 1
    assert saida["resolved"]["card"]["name"] == "Nubank"
    item = saida["items"][0]
    assert item["amount"] == "100.00" and item["my_share"] == "50.00" and item["card"] == "Nubank"
    assert saida["my_share_totals"][0]["amount"] == "50.00"


def test_busca_por_pessoa(mcp_client, c):
    cria_despesa(mcp_client, c.alice, c.casa, title="Jantar", amount="90.00", day=c.hoje, split_with=[c.joao])
    cria_despesa(mcp_client, c.alice, c.casa, title="Só meu", amount="10.00", day=c.hoje)
    saida = ok(call_tool(mcp_client, c.token, "transactions_search", {"person": "João"}))
    assert [i["title"] for i in saida["items"]] == ["Jantar"]


def test_busca_por_categoria_em_varios_espacos(mcp_client, db_session, c):
    cria_despesa(mcp_client, c.alice, c.pessoal, title="Almoço", amount="30.00", day=c.hoje,
                 category_id=categoria(db_session, c.pessoal, "Alimentação"))
    cria_despesa(mcp_client, c.alice, c.casa, title="Pizza", amount="60.00", day=c.hoje,
                 category_id=categoria(db_session, c.casa, "Alimentação"))
    saida = ok(call_tool(mcp_client, c.token, "transactions_search", {"category": "alimentacao"}))
    assert {i["title"] for i in saida["items"]} == {"Almoço", "Pizza"}


def test_busca_paginada_com_cursor(mcp_client, c):
    for i in range(5):
        cria_despesa(mcp_client, c.alice, c.pessoal, title=f"Item {i}", amount="1.00", day=c.hoje)
    primeira = ok(call_tool(mcp_client, c.token, "transactions_search", {"limit": 2}))
    assert primeira["total_count"] == 5 and len(primeira["items"]) == 2 and primeira["next_cursor"]
    segunda = ok(call_tool(mcp_client, c.token, "transactions_search", {"limit": 2, "cursor": primeira["next_cursor"]}))
    assert {i["id"] for i in segunda["items"]}.isdisjoint({i["id"] for i in primeira["items"]})
    trocado = err(call_tool(mcp_client, c.token, "transactions_search", {"limit": 2, "text": "x", "cursor": primeira["next_cursor"]}))
    assert trocado["code"] == "VALIDATION_ERROR"


def test_limite_maximo_de_pagina(mcp_client, c):
    erro = err(call_tool(mcp_client, c.token, "transactions_search", {"limit": 500}))
    assert erro["code"] == "VALIDATION_ERROR"


def test_nao_aceita_sql_nem_filtro_desconhecido(mcp_client, c):
    erro = err(call_tool(mcp_client, c.token, "transactions_search", {"where": "1=1"}))
    assert erro["code"] == "VALIDATION_ERROR"


def test_texto_com_curinga_nao_casa_tudo(mcp_client, c):
    cria_despesa(mcp_client, c.alice, c.pessoal, title="Padaria", amount="5.00", day=c.hoje)
    saida = ok(call_tool(mcp_client, c.token, "transactions_search", {"text": "%"}))
    assert saida["total_count"] == 0


def test_transactions_get_completo(mcp_client, c):
    criado = cria_despesa(mcp_client, c.alice, c.casa, title="Mercado", amount="100.01", day=c.hoje,
                          card=c.nubank, split_with=[c.joao])
    tx = ok(call_tool(mcp_client, c.token, "transactions_get", {"transaction_id": criado["id"]}))["transaction"]
    assert tx["space"]["name"] == "Casa"
    assert tx["card"]["name"] == "Nubank" and tx["statement"]["month"]
    partes = {s["person"]["name"]: s["amount"] for s in tx["split"]}
    assert partes == {"Alice Souza": "50.01", "João Pereira": "50.00"}  # centavo aos primeiros (ADR 0001)
    assert sum(Decimal(v) for v in partes.values()) == Decimal("100.01")
    assert tx["my_share"] == "50.01"


def test_parcelas_somam_o_total(mcp_client, c):
    criado = cria_despesa(mcp_client, c.alice, c.pessoal, title="TV", amount="1000.00", day=c.hoje,
                          card=c.nubank, installments=3)
    grupo = criado["installment_group_id"]
    saida = ok(call_tool(mcp_client, c.token, "transactions_search", {"installment_group_id": grupo, "sort": "date_asc"}))
    assert [i["installment"] for i in saida["items"]] == ["1/3", "2/3", "3/3"]
    assert [i["amount"] for i in saida["items"]] == ["333.34", "333.33", "333.33"]


def test_statements_get(mcp_client, db_session, c):
    cria_despesa(mcp_client, c.alice, c.pessoal, title="Gasolina", amount="89.90", day=c.hoje, card=c.nubank,
                 category_id=categoria(db_session, c.pessoal, "Transporte"))
    # A compra de HOJE cai na fatura do ciclo atual — a mesma que cards_list aponta.
    mes = ok(call_tool(mcp_client, c.token, "cards_list"))["cards"][0]["current_statement"]["month"]
    fatura = ok(call_tool(mcp_client, c.token, "statements_get", {"card": "Nubank", "month": mes}))
    assert fatura["exists"] is True
    assert fatura["purchases"][0]["title"] == "Gasolina"
    assert fatura["purchases"][0]["statement_amount"] == "89.90"
    assert fatura["by_category"] == [{"category": "Transporte", "amount": "89.90", "count": 1}]
    assert fatura["total"] == "89.90" and fatura["balance"] == "89.90"
    # Sem cartão informado: o único cartão da pessoa.
    assert ok(call_tool(mcp_client, c.token, "statements_get"))["card"]["name"] == "Nubank"


def test_statements_get_mes_sem_fatura_nao_cria_nada(mcp_client, db_session, c):
    from sqlmodel import select
    from app.models.credit_card import CardStatement

    fatura = ok(call_tool(mcp_client, c.token, "statements_get", {"card": "Nubank", "month": "2020-01"}))
    assert fatura["exists"] is False and fatura["status"] == "not_created"
    assert db_session.exec(select(CardStatement)).all() == []


def test_reports_summary_por_categoria(mcp_client, db_session, c):
    cria_despesa(mcp_client, c.alice, c.casa, title="Pizza", amount="60.00", day=c.hoje, split_with=[c.joao],
                 category_id=categoria(db_session, c.casa, "Alimentação"))
    cria_despesa(mcp_client, c.alice, c.pessoal, title="Almoço", amount="40.00", day=c.hoje,
                 category_id=categoria(db_session, c.pessoal, "Alimentação"))
    saida = ok(call_tool(mcp_client, c.token, "reports_summary", {"category": "alimentação"}))
    assert saida["my_categories"] == [{"category": "Alimentação", "amount": "70.00", "currency": "BRL"}]
    assert saida["consumption"] == "70.00"


def test_debts_summary_joao_me_deve(mcp_client, c):
    cria_despesa(mcp_client, c.alice, c.casa, title="Jantar", amount="90.00", day=c.hoje, split_with=[c.joao])
    saida = ok(call_tool(mcp_client, c.token, "debts_summary", {"person": "João"}))
    linha = saida["spaces"][0]["balances"][0]
    assert linha["person"]["name"] == "João Pereira"
    assert linha["direction"] == "owes_you" and linha["amount"] == "45.00"


def test_payables_list(mcp_client, c):
    cria_despesa(mcp_client, c.alice, c.pessoal, title="Luz", amount="150.00", day=c.hoje + timedelta(days=3))
    saida = ok(call_tool(mcp_client, c.token, "payables_list"))
    assert "Luz" in {b["title"] for b in saida["bills"]} or saida["bills_total"] is not None


def test_income_e_recorrencias_vazias(mcp_client, c):
    assert ok(call_tool(mcp_client, c.token, "income_list"))["incomes"] == []
    assert ok(call_tool(mcp_client, c.token, "recurring_list"))["items"] == []
    assert ok(call_tool(mcp_client, c.token, "budgets_list"))["budgets"] == []
