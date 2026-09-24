"""Extrato de CONTA pelo agente (ADR 0037) e `imports_undo` (ADR 0036/0037).

As tools chamam o MESMO comando da tela (`commands/account_imports.py`,
`commands/imports.py`); aqui se confere o caminho da IA: a prévia sugere, a
gravação traduz nomes em ids e devolve os problemas, os escopos certos são
exigidos, e o desfazer só executa com o token da prévia.
"""
from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlmodel import select

from app.models.account_ledger import AccountTransfer
from app.models.income import Income
from app.models.payment_account import PaymentAccount
from app.services.oauth import scopes as escopos
from tests.mcp.conftest import call_tool, err, issue_token, ok
from tests.mcp.scenario import monta


@pytest.fixture
def c(db_session, mcp_client):
    cena = monta(db_session, mcp_client)
    db_session.add(PaymentAccount(name="Poupança", owner_user_id=cena.alice.id, currency="BRL"))
    db_session.commit()
    return cena


def _dia(c, delta=1):
    return (c.hoje - timedelta(days=delta)).isoformat()


def _linhas(c):
    return [
        {"line": 2, "date": _dia(c, 3), "title": "SALARIO EMPRESA", "amount": "5000.00", "direction": "in", "external_id": "X1"},
        {"line": 3, "date": _dia(c, 2), "title": "MERCADO", "amount": "89.90", "direction": "out", "external_id": "X2"},
        {"line": 4, "date": _dia(c, 1), "title": "TRANSF MESMA TITULARIDADE POUPANCA", "amount": "1000.00",
         "direction": "out", "external_id": "X3"},
    ]


def test_previa_de_extrato_sugere_e_marca_o_ja_importado(mcp_client, db_session, c):
    previa = ok(call_tool(mcp_client, c.token, "imports_preview", {"account": "Itaú", "rows": _linhas(c)}))
    assert previa["account"]["name"] == "Itaú" and previa["space"] is None
    assert [(r["direction"], r["suggestion"]) for r in previa["rows"]] == [("in", "income"), ("out", "expense"), ("out", "transfer")]
    assert previa["rows"][2]["suggested_account"]["name"] == "Poupança"

    ok(call_tool(mcp_client, c.token, "imports_commit", {
        "idempotency_key": str(uuid4()), "account": "Itaú", "space": "Casa",
        "rows": [dict(_linhas(c)[0]), dict(_linhas(c)[1])],
    }))
    de_novo = ok(call_tool(mcp_client, c.token, "imports_preview", {"account": "Itaú", "rows": _linhas(c)}))
    assert [r["already_imported"] for r in de_novo["rows"]] == [True, True, False]


def test_gravacao_traduz_nomes_e_devolve_os_problemas(mcp_client, db_session, c):
    linhas = _linhas(c)
    linhas[2]["classification"] = "transfer"
    linhas[2]["counterpart_account"] = "Poupança"
    linhas.append({"line": 5, "date": _dia(c), "title": "FEIRA", "amount": "20.00", "direction": "out"})
    r = ok(call_tool(mcp_client, c.token, "imports_commit", {
        "idempotency_key": str(uuid4()), "account": "Itaú", "label": "Itaú setembro",
        "rows": linhas[:1] + [dict(linhas[1], space="Casa", category="Mercado")] + linhas[2:],
    }))
    assert r["by_classification"] == {"income": 1, "expense": 1, "transfer": 1}
    assert r["problems"] == [{"line": 5, "reason": "escolha o espaço da despesa"}]
    assert r["account"]["name"] == "Itaú" and r["space"] is None
    assert db_session.exec(select(Income).where(Income.title == "SALARIO EMPRESA")).one().account_id == c.conta.id
    assert db_session.exec(select(AccountTransfer)).one().from_account_id == c.conta.id


def test_renda_e_transferencia_pedem_os_escopos_de_conta_e_renda(mcp_client, db_session, c):
    so_lancamentos = issue_token(db_session, c.alice, [escopos.FINANCE_READ, escopos.TRANSACTIONS_WRITE])
    erro = err(call_tool(mcp_client, so_lancamentos, "imports_commit", {
        "idempotency_key": str(uuid4()), "account": "Itaú", "rows": [_linhas(c)[0]],
    }))
    assert erro["code"] == "PERMISSION_DENIED"
    # Só despesas: o escopo de lançamentos basta.
    feito = ok(call_tool(mcp_client, so_lancamentos, "imports_commit", {
        "idempotency_key": str(uuid4()), "account": "Itaú", "space": "Casa", "rows": [_linhas(c)[1]],
    }))
    assert feito["by_classification"] == {"expense": 1}


def test_desfazer_so_com_o_token_da_previa(mcp_client, db_session, c):
    lote = ok(call_tool(mcp_client, c.token, "imports_commit", {
        "idempotency_key": str(uuid4()), "account": "Itaú", "space": "Casa",
        "rows": [_linhas(c)[0], _linhas(c)[1]],
    }))["batch_id"]
    previa = ok(call_tool(mcp_client, c.token, "imports_undo", {"batch_id": lote}))
    assert (previa["mode"], previa["will_undo"]) == ("preview", {"income": 1, "expense": 1})
    # Sem executar nada ainda.
    assert db_session.exec(select(Income).where(Income.deleted_at.is_(None))).all() != []
    # Token de outra pessoa não serve (e o lote dela nem aparece).
    assert err(call_tool(mcp_client, c.token_bob, "imports_undo", {"batch_id": lote}))["code"] == "NOT_FOUND"

    feito = ok(call_tool(mcp_client, c.token, "imports_undo", {"batch_id": lote, "confirmation_token": previa["confirmation_token"]}))
    assert (feito["mode"], feito["undone"]) == ("done", {"income": 1, "expense": 1})
    db_session.expire_all()
    assert db_session.exec(select(Income).where(Income.deleted_at.is_(None))).all() == []
    # Repetir com o mesmo token devolve o mesmo resultado (retry de rede).
    assert ok(call_tool(mcp_client, c.token, "imports_undo", {"batch_id": lote, "confirmation_token": previa["confirmation_token"]}))["undone"] == feito["undone"]


def test_desfazer_lote_de_despesas_pelo_mesmo_caminho(mcp_client, db_session, c):
    lote = ok(call_tool(mcp_client, c.token, "imports_commit", {
        "idempotency_key": str(uuid4()), "space": "Casa",
        "rows": [{"date": _dia(c), "title": "Uber", "amount": "23.00"}],
    }))["batch_id"]
    previa = ok(call_tool(mcp_client, c.token, "imports_undo", {"batch_id": lote}))
    assert previa["will_undo"] == {"expense": 1}
    feito = ok(call_tool(mcp_client, c.token, "imports_undo", {"batch_id": lote, "confirmation_token": previa["confirmation_token"]}))
    assert feito["undone"] == {"expense": 1}
    # Nada mais vivo: a prévia diz que não há o que desfazer.
    assert ok(call_tool(mcp_client, c.token, "imports_undo", {"batch_id": lote}))["confirmation_token"] is None


def test_token_de_uma_previa_velha_nao_desfaz_o_que_mudou(mcp_client, db_session, c):
    lote = ok(call_tool(mcp_client, c.token, "imports_commit", {
        "idempotency_key": str(uuid4()), "space": "Casa",
        "rows": [{"date": _dia(c), "title": "Uber", "amount": "23.00"}, {"date": _dia(c), "title": "Táxi", "amount": "30.00"}],
    }))
    previa = ok(call_tool(mcp_client, c.token, "imports_undo", {"batch_id": lote["batch_id"]}))
    ok(call_tool(mcp_client, c.token, "transactions_delete", {"transaction_id": lote["transaction_ids"][0]}))
    erro = err(call_tool(mcp_client, c.token, "imports_undo", {"batch_id": lote["batch_id"], "confirmation_token": previa["confirmation_token"]}))
    assert erro["code"] == "CONFLICT"


def test_lista_traz_os_lotes_de_extrato(mcp_client, db_session, c):
    ok(call_tool(mcp_client, c.token, "imports_commit", {
        "idempotency_key": str(uuid4()), "account": "Itaú", "rows": [_linhas(c)[0]],
    }))
    lote = ok(call_tool(mcp_client, c.token, "imports_list", {}))["batches"][0]
    assert (lote["kind"], lote["account"]["name"], lote["space"], lote["live_transactions"]) == ("account", "Itaú", None, 1)
    linhas = ok(call_tool(mcp_client, c.token, "imports_list", {"batch_id": lote["id"]}))["rows"]
    assert [(r["direction"], r["classification"], r["status"]) for r in linhas] == [("in", "income", "imported")]


def test_previa_de_despesas_so_marca_o_que_ainda_existe(mcp_client, db_session, c):
    """A mesma regra do commit (ADR 0036): excluído, a linha volta a ser nova."""
    linha = {"date": _dia(c), "title": "Uber", "amount": "23.00"}
    lote = ok(call_tool(mcp_client, c.token, "imports_commit", {"idempotency_key": str(uuid4()), "space": "Casa", "rows": [linha]}))
    assert ok(call_tool(mcp_client, c.token, "imports_preview", {"space": "Casa", "rows": [linha]}))["rows"][0]["already_imported"] is True
    ok(call_tool(mcp_client, c.token, "transactions_delete", {"transaction_id": lote["transaction_ids"][0]}))
    assert ok(call_tool(mcp_client, c.token, "imports_preview", {"space": "Casa", "rows": [linha]}))["rows"][0]["already_imported"] is False
