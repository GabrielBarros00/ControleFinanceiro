"""O que o COMPONENTE recebe além dos dados (ADR 0035 §11): vista, modo, editar e desfazer.

O `_meta` não vai para o modelo; é o que deixa a pessoa editar e desfazer ali mesmo.
O desfazer é só um convite: o servidor reaplica toda regra quando o botão é
clicado — por isso os testes EXECUTAM o `undo` e conferem o efeito.
"""
from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

import pytest

from app.mcp import ui_results
from tests.mcp.conftest import call_tool, err, issue_token, ok
from tests.mcp.scenario import cria_despesa, monta


@pytest.fixture
def c(db_session, mcp_client):
    return monta(db_session, mcp_client)


def _cria(mcp_client, c, **args) -> dict:
    return call_tool(mcp_client, c.token, "transactions_create", {"idempotency_key": str(uuid4()), **args})


def _executa(mcp_client, token, undo: dict) -> dict:
    return ok(call_tool(mcp_client, token, undo["tool"], undo["args"]))


def test_criacao_desenha_com_editar_e_desfazer(mcp_client, db_session, c):
    r = _cria(mcp_client, c, title="Mercado", amount="80.00", category="Mercado", space="Casa", split_with=["João"])
    meta = r["_meta"]
    assert (meta["view"], meta["mode"], meta["tool"], meta["can_edit"]) == ("transaction", "created", "transactions_create", True)
    form = meta["form"]
    assert {"Mercado", "Alimentação"} <= {x["name"] for x in form["categories"]}
    assert [x["name"] for x in form["cards"]] == ["Nubank"] and [x["name"] for x in form["accounts"]] == ["Itaú"]
    assert {(p["name"], p["me"]) for p in form["people"]} == {("Alice Souza", True), ("João Pereira", False)}
    assert meta["undo"]["tool"] == "transactions_delete"
    # O modelo não vê o `_meta`: nada de opções do editor no texto dele.
    assert "payment_methods" not in r["content"][0]["text"]

    _executa(mcp_client, c.token, meta["undo"])
    assert err(call_tool(mcp_client, c.token, "transactions_get", {"transaction_id": r["structuredContent"]["transaction"]["id"]}))["code"] == "NOT_FOUND"


def test_edicao_simples_se_desfaz_e_complexa_nao(mcp_client, db_session, c):
    tx = ok(_cria(mcp_client, c, title="Padaria", amount="12.00", category="Alimentação"))["transaction"]
    r = call_tool(mcp_client, c.token, "transactions_update", {"transaction_id": tx["id"], "amount": "15.00", "title": "Padaria Pão Quente"})
    undo = r["_meta"]["undo"]
    assert undo["tool"] == "transactions_update"
    assert undo["args"]["amount"] == "12.00" and undo["args"]["title"] == "Padaria" and undo["args"]["expected_version"]
    volta = _executa(mcp_client, c.token, undo)["transaction"]
    assert (volta["amount"], volta["title"]) == ("12.00", "Padaria")
    # Desfazer em cima de uma versão velha não sobrescreve a mudança de outra pessoa.
    assert err(call_tool(mcp_client, c.token, undo["tool"], undo["args"]))["code"] == "CONFLICT"

    complexa = call_tool(mcp_client, c.token, "transactions_update", {"transaction_id": tx["id"], "payment_method": "pix"})
    assert "undo" not in complexa["_meta"] and complexa["_meta"]["mode"] == "updated"


def test_exclusao_desenha_e_desfaz(mcp_client, db_session, c):
    tx = ok(_cria(mcp_client, c, title="Cinema", amount="40.00"))["transaction"]
    r = call_tool(mcp_client, c.token, "transactions_delete", {"transaction_id": tx["id"]})
    assert (r["_meta"]["view"], r["_meta"]["mode"]) == ("transaction", "deleted")
    _executa(mcp_client, c.token, r["_meta"]["undo"])
    assert ok(call_tool(mcp_client, c.token, "transactions_get", {"transaction_id": tx["id"]}))["transaction"]["title"] == "Cinema"


def test_quem_nao_pode_editar_nao_recebe_editor(mcp_client, db_session, c):
    tx = cria_despesa(mcp_client, c.alice, c.casa, title="Jantar", amount="90.00", day=c.hoje, split_with=[c.joao])
    token_joao = issue_token(db_session, c.joao)
    r = call_tool(mcp_client, token_joao, "transactions_restore", {"transaction_id": tx["id"]})
    # João é member e o lançamento é da Alice: nem edita nem vê o editor.
    assert err(r)["code"] == "PERMISSION_DENIED"
    so_leitura = issue_token(db_session, c.alice, ["finance.read"])
    visto = call_tool(mcp_client, so_leitura, "transactions_show", {"transaction_id": tx["id"]})
    assert "form" not in visto["_meta"] and "undo" not in visto["_meta"]


def test_recibos_das_outras_escritas(mcp_client, db_session, c):
    renda = call_tool(mcp_client, c.token, "income_create", {"idempotency_key": str(uuid4()), "title": "Freela", "amount": "500.00"})
    assert renda["_meta"]["view"] == "income" and renda["_meta"]["undo"]["tool"] == "income_delete"
    _executa(mcp_client, c.token, renda["_meta"]["undo"])
    cat = call_tool(mcp_client, c.token, "categories_create", {"kind": "tag", "name": "Temporária", "space": "Casa"})
    assert cat["_meta"]["view"] == "receipt" and cat["_meta"]["tool"] == "categories_create"
    _executa(mcp_client, c.token, cat["_meta"]["undo"])
    assert err(call_tool(mcp_client, c.token, "categories_update", {"kind": "tag", "name": "Temporária", "space": "Casa", "new_name": "x"}))["code"] == "NOT_FOUND"


def test_falha_no_meta_nao_desfaz_a_escrita(mcp_client, db_session, c, monkeypatch):
    def explode(call, dados):
        raise RuntimeError("bug no componente")

    monkeypatch.setitem(ui_results.MONTADORES, "transactions_create", explode)
    r = _cria(mcp_client, c, title="Farmácia", amount="25.00")
    assert not r.get("isError")
    tx = r["structuredContent"]["transaction"]
    assert ok(call_tool(mcp_client, c.token, "transactions_get", {"transaction_id": tx["id"]}))["transaction"]["amount"] == "25.00"


def test_view_show_desenha_a_mesma_leitura_da_tool_de_dados(mcp_client, c):
    for t in ("Uber", "Padaria"):
        ok(_cria(mcp_client, c, title=t, amount="10.00"))
    tela = call_tool(mcp_client, c.token, "view_show", {"view": "transactions", "text": "Uber"})
    dados = ok(call_tool(mcp_client, c.token, "transactions_search", {"text": "Uber"}))
    assert tela["structuredContent"]["source_tool"] == "transactions_search"
    assert tela["structuredContent"]["data"]["total_count"] == dados["total_count"] == 1
    assert tela["_meta"]["view"] == "transactions"
    assert tela["_meta"]["query"] == {"tool": "transactions_search", "args": {"text": "Uber"}}


def test_view_show_recusa_campo_que_a_tela_nao_usa(mcp_client, c):
    erro = err(call_tool(mcp_client, c.token, "view_show", {"view": "budgets", "text": "x"}))
    assert erro["code"] == "VALIDATION_ERROR" and "não usa text" in erro["message"]
    assert err(call_tool(mcp_client, c.token, "view_show", {"view": "breakdown"}))["code"] == "VALIDATION_ERROR"


# --- O que o componente chama tem de ser chamável por ele -----------------------------

_WIDGET = Path(__file__).resolve().parents[3] / "frontend" / "src" / "mcp-widget"


def _nomes_citados(texto: str) -> set[str]:
    import app.mcp.tools  # noqa: F401  (registra as tools)
    from app.mcp.registry import REGISTRY

    return {n for n in re.findall(r"['\"]([a-z]+(?:_[a-z]+)+)['\"]", texto) if n in REGISTRY}


def test_toda_tool_que_o_componente_chama_e_chamavel_por_ele():
    """Host que honra `visibility` recusa `tools/call` do componente para tool só do
    modelo: o botão falharia em produção, e só lá. A varredura lê o código do
    componente (fora os testes) e o `ui_results.py` (as tools de Desfazer)."""
    from app.mcp.registry import REGISTRY

    fontes = [p for p in _WIDGET.rglob("*.ts*") if "__tests__" not in p.parts]
    citadas = set().union(*(_nomes_citados(p.read_text(encoding="utf-8")) for p in fontes))
    desfazer = set(re.findall(r'ui_meta\.undo\(\s*"([a-z_]+)"', Path(ui_results.__file__).read_text(encoding="utf-8")))
    # Denominador: uma varredura que não acha nada passaria calada.
    assert len(citadas) >= 25 and len(desfazer) >= 10, (len(citadas), len(desfazer))
    fora = sorted(n for n in citadas | desfazer if not REGISTRY[n].app_callable)
    assert not fora, f"o componente chama tools que não são app_callable: {fora}"
