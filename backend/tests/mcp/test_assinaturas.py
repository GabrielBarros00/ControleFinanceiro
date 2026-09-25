"""Assinaturas pelo agente (ADR 0039).

As tools de recorrência chamam o MESMO comando da tela; aqui se confere o
caminho da IA: plano e teste grátis marcam a assinatura, o provedor é o
estabelecimento, e a lista responde "quanto pago de assinaturas por mês".
"""
from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from tests.mcp.conftest import call_tool, err, ok
from tests.mcp.scenario import monta


@pytest.fixture
def c(db_session, mcp_client):
    return monta(db_session, mcp_client)


def _cria(mcp_client, c, **extra):
    corpo = {"idempotency_key": str(uuid4()), "title": "Assinatura", "amount": "50.00", "space": "Casa", **extra}
    return ok(call_tool(mcp_client, c.token, "recurring_create", corpo))["recurring"]


def test_plano_e_teste_gratis_marcam_a_assinatura_e_o_provedor_e_o_estabelecimento(mcp_client, db_session, c):
    fim = c.hoje + timedelta(days=15)
    r = _cria(mcp_client, c, title="Netflix", amount="55.90", plan="Premium", trial_ends_on=fim.isoformat(),
              notes="4 telas", merchant="Netflix")
    assert r["subscription"] == {"plan": "Premium", "trial_ends_on": fim.isoformat(), "notes": "4 telas"}
    assert r["merchant"]["name"] == "Netflix"
    # Sem início: a primeira cobrança é no fim do teste.
    assert (r["start_date"], r["next_occurrence"]) == (fim.isoformat(), fim.isoformat())
    lista = ok(call_tool(mcp_client, c.token, "categories_list", {"space": "Casa"}))
    assert [m["name"] for m in lista["merchants"]] == ["Netflix"]


def test_lista_so_das_assinaturas_com_o_custo_por_mes(mcp_client, db_session, c):
    _cria(mcp_client, c, title="Domínio", amount="120.00", frequency="yearly", month_of_year=c.hoje.month, subscription=True)
    _cria(mcp_client, c, title="Academia", amount="99.90", subscription=True)
    _cria(mcp_client, c, title="Aluguel", amount="2000.00")
    lista = ok(call_tool(mcp_client, c.token, "recurring_list", {"subscriptions_only": True}))
    assert sorted(i["title"] for i in lista["items"]) == ["Academia", "Domínio"]
    assert lista["monthly_my_share"] == {"BRL": "109.90"}
    dominio = next(i for i in lista["items"] if i["title"] == "Domínio")
    assert dominio["my_monthly"] == "10.00"


def test_editar_apaga_plano_desmarca_e_solta_o_provedor(mcp_client, db_session, c):
    r = _cria(mcp_client, c, title="Spotify", plan="Família", merchant="Spotify")
    alterado = ok(call_tool(mcp_client, c.token, "recurring_update", {"recurring_id": r["id"], "plan": ""}))
    assert alterado["recurring"]["subscription"]["plan"] is None and "subscription" in alterado["changed"]
    alterado = ok(call_tool(mcp_client, c.token, "recurring_update", {"recurring_id": r["id"], "merchant": ""}))
    assert alterado["recurring"]["merchant"] is None and alterado["changed"] == ["merchant"]
    alterado = ok(call_tool(mcp_client, c.token, "recurring_update", {"recurring_id": r["id"], "subscription": False}))
    assert alterado["recurring"]["subscription"] is None


def test_provedor_parecido_vira_pergunta(mcp_client, db_session, c):
    ok(call_tool(mcp_client, c.token, "categories_create", {"kind": "merchant", "name": "Smart Fit", "space": "Casa"}))
    r = err(call_tool(mcp_client, c.token, "recurring_create", {
        "idempotency_key": str(uuid4()), "title": "Academia", "amount": "99.90", "space": "Casa",
        "subscription": True, "merchant": "SmartFit",
    }))
    assert r["code"] == "AMBIGUOUS" and r["candidates"][0]["name"] == "Smart Fit"


def test_renda_nao_e_assinatura(mcp_client, db_session, c):
    r = err(call_tool(mcp_client, c.token, "recurring_create", {
        "idempotency_key": str(uuid4()), "kind": "income", "title": "Salário", "amount": "4000.00", "plan": "CLT",
    }))
    assert r["code"] == "VALIDATION_ERROR" and "plan" in r["message"]
