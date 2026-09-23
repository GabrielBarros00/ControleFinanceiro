"""Isolamento entre usuários (A×B): nenhuma tool alcança o que é do outro.

Alice monta um cenário completo (espaço, lançamento, parcelada, cartão com
fatura, conta, renda, recorrência, acerto, meta). Bob — que NÃO divide espaço com
ela — chama TODAS as tools que recebem um identificador, com os ids da Alice.
Cada chamada tem de falhar sem vazar nada: nem o título, nem o valor, nem a
existência (a resposta é a mesma de um id que não existe).

E a varredura tem denominador (`varredura-sem-denominador-passa-vazia`): toda
tool do registro que tem parâmetro `*_id` precisa aparecer aqui, senão o teste
de cobertura falha — uma tool nova com id não entra sem o seu caso A×B.
"""
from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from app.mcp.registry import REGISTRY, input_schema
from app.mcp.server import get_server
from app.models.estimate import MonthlyEstimate
from app.models.recurring import RecurringExpense
from tests.mcp.conftest import call_tool, err, ok
from tests.mcp.scenario import cria_despesa, monta

SEGREDO = "Segredo-da-Alice"


@pytest.fixture
def mundo(db_session, mcp_client):
    c = monta(db_session, mcp_client)
    avulsa = cria_despesa(mcp_client, c.alice, c.casa, title=SEGREDO, amount="777.77", day=c.hoje, split_with=[c.joao])
    parcelada = cria_despesa(mcp_client, c.alice, c.pessoal, title=SEGREDO + " TV", amount="3000.00",
                             day=c.hoje - timedelta(days=45), card=c.nubank, installments=3)
    renda = ok(call_tool(mcp_client, c.token, "income_create", {
        "idempotency_key": str(uuid4()), "title": SEGREDO, "amount": "5000.00",
    }))["income"]
    acerto = ok(call_tool(mcp_client, c.token, "settlements_create", {
        "idempotency_key": str(uuid4()), "person": "João", "direction": "they_paid_me", "amount": "100.00",
    }))
    recorrente = ok(call_tool(mcp_client, c.token, "recurring_create", {
        "idempotency_key": str(uuid4()), "title": SEGREDO, "amount": "10.00", "materialize": "future",
    }))["recurring"]
    return {
        "c": c,
        "tx": avulsa["id"],
        "parcela": parcelada["id"],
        "grupo": parcelada["installment_group_id"],
        "renda": renda["id"],
        "acerto": acerto["id"],
        "recorrente": recorrente["id"],
    }


def _casos(m: dict) -> dict[str, list[dict]]:
    c = m["c"]
    k = lambda: str(uuid4())  # noqa: E731
    return {
        "people_list": [{"space_id": c.casa.id}],
        "categories_list": [{"space_id": c.casa.id}],
        "transactions_search": [{"space_id": c.casa.id}, {"card_id": c.nubank.id}, {"account_id": c.conta.id},
                                {"person_id": c.alice.id}, {"installment_group_id": m["grupo"]}],
        "transactions_get": [{"transaction_id": m["tx"]}, {"transaction_id": m["parcela"]}],
        "statements_get": [{"card_id": c.nubank.id}],
        "reports_summary": [{"space_id": c.casa.id}],
        "budgets_list": [{"space_id": c.casa.id}],
        "debts_summary": [{"space_id": c.casa.id}, {"person_id": c.alice.id}],
        "recurring_list": [{"space_id": c.casa.id}],
        "payables_list": [{"space_id": c.casa.id}],
        "transactions_create": [
            {"idempotency_key": k(), "title": "x", "amount": "1", "space_id": c.casa.id},
            {"idempotency_key": k(), "title": "x", "amount": "1", "card_id": c.nubank.id},
            {"idempotency_key": k(), "title": "x", "amount": "1", "account_id": c.conta.id},
            {"idempotency_key": k(), "title": "x", "amount": "1", "split_with_ids": [c.alice.id]},
            {"idempotency_key": k(), "title": "x", "amount": "1", "paid_by_id": c.alice.id, "split_with_ids": [c.alice.id]},
        ],
        "transactions_update": [{"transaction_id": m["tx"], "title": "hack"},
                                {"transaction_id": m["parcela"], "scope": "purchase", "amount": "1.00"}],
        "transactions_delete": [{"transaction_id": m["tx"]}, {"transaction_id": m["parcela"], "scope": "purchase"}],
        "transactions_restore": [{"transaction_id": m["tx"]}],
        "transactions_bulk_preview": [{"action": "delete", "transaction_ids": [m["tx"], m["parcela"]]},
                                      {"action": "delete", "filters": {"space_id": c.casa.id}}],
        "imports_preview": [{"space_id": c.casa.id, "rows": [{"date": c.hoje.isoformat(), "title": SEGREDO, "amount": "777.77"}]}],
        "imports_commit": [{"idempotency_key": k(), "space_id": c.casa.id,
                            "rows": [{"date": c.hoje.isoformat(), "title": "x", "amount": "1"}]}],
        "statements_pay": [{"idempotency_key": k(), "card_id": c.nubank.id}],
        "transfers_create": [{"idempotency_key": k(), "from_account_id": c.conta.id, "to_account_id": c.conta.id, "amount": "1"}],
        "accounts_adjust_balance": [{"idempotency_key": k(), "account_id": c.conta.id, "real_balance": "1"}],
        "income_create": [{"idempotency_key": k(), "title": "x", "amount": "1", "account_id": c.conta.id}],
        "income_update": [{"income_id": m["renda"], "amount": "1.00"}, {"income_id": m["renda"], "status": "cancelled"}],
        "settlements_create": [{"idempotency_key": k(), "person_id": c.alice.id, "direction": "i_paid_them",
                                "amount": "1", "space_id": c.casa.id}],
        "settlements_delete": [{"settlement_id": m["acerto"]}],
        "recurring_create": [{"idempotency_key": k(), "title": "x", "amount": "1", "space_id": c.casa.id}],
        "recurring_update": [{"recurring_id": m["recorrente"], "amount": "1.00"}],
        "budgets_set": [{"space_id": c.casa.id, "category": "Alimentação", "amount": "1", "scope": "personal"}],
        "categories_create": [{"space_id": c.casa.id, "name": "Invasão"}],
    }


def _tem_id(nome: str) -> bool:
    props = input_schema(REGISTRY[nome]).get("properties", {})
    texto = str(props)
    return any(p.endswith("_id") or p.endswith("_ids") for p in props) or "_id'" in texto


def test_toda_tool_com_id_tem_caso_de_isolamento(db_session, mcp_client):
    get_server()
    com_id = {n for n in REGISTRY if _tem_id(n)}
    assert len(com_id) >= 25, com_id  # denominador: a varredura enxerga as tools
    faltando = com_id - set(_casos({"c": _Falso(), **{k: 0 for k in ("tx", "parcela", "grupo", "renda", "acerto", "recorrente")}}))
    assert not faltando, f"tools com id sem caso A×B: {sorted(faltando)}"


class _Falso:
    def __getattr__(self, nome):
        return self

    id = 0

    def isoformat(self):
        return "2026-01-01"


def test_bob_nao_alcanca_nada_da_alice(db_session, mcp_client, mundo):
    c = mundo["c"]
    antes = _fotografia(db_session)
    vazamentos, aceitas = [], []
    for nome, chamadas in _casos(mundo).items():
        for argumentos in chamadas:
            resultado = call_tool(mcp_client, c.token_bob, nome, argumentos)
            texto = str(resultado)
            if SEGREDO in texto or "777.77" in texto or "Alice" in texto:
                vazamentos.append((nome, argumentos))
            if not resultado.get("isError"):
                aceitas.append((nome, argumentos, resultado.get("structuredContent")))
            else:
                # Nunca PERMISSION_DENIED: "existe mas não é seu" já seria vazamento.
                assert err(resultado)["code"] in {"NOT_FOUND", "VALIDATION_ERROR"}, (nome, argumentos, resultado)
    assert not vazamentos, vazamentos
    # As únicas chamadas que "funcionam" para o Bob são buscas que simplesmente não acham nada.
    for nome, argumentos, saida in aceitas:
        assert nome in {"transactions_search", "debts_summary", "transactions_bulk_preview"}, (nome, argumentos, saida)
        if nome == "transactions_search":
            assert saida["total_count"] == 0
        if nome == "transactions_bulk_preview":
            assert saida["count"] == 0 and saida["confirmation_token"] is None
    assert _fotografia(db_session) == antes, "o Bob alterou dados da Alice"


def _fotografia(db) -> dict:
    """Estado observável do que é da Alice — tem de sair idêntico."""
    from sqlmodel import select

    from app.models.category import Category
    from app.models.credit_card import StatementPayment
    from app.models.income import Income
    from app.models.settlement import Settlement
    from app.models.transaction import Transaction

    db.expire_all()
    return {
        "tx": sorted((t.id, t.title, str(t.total_amount), t.deleted_at is None, t.status) for t in db.exec(select(Transaction)).all()),
        "renda": sorted((r.id, str(r.amount), r.cancelled_at is None) for r in db.exec(select(Income)).all()),
        "acertos": sorted((s.id, s.deleted_at is None) for s in db.exec(select(Settlement)).all()),
        "rec": sorted((r.id, str(r.base_amount)) for r in db.exec(select(RecurringExpense)).all()),
        "metas": len(db.exec(select(MonthlyEstimate)).all()),
        "cats": len(db.exec(select(Category)).all()),
        "pagamentos": len(db.exec(select(StatementPayment)).all()),
    }


def test_joao_ve_so_o_que_o_envolve(db_session, mcp_client, mundo):
    """Membro da casa sem visão total: não vê a compra pessoal da Alice nem a renda dela."""
    from tests.mcp.conftest import issue_token

    c = mundo["c"]
    token_joao = issue_token(db_session, c.joao)
    assert err(call_tool(mcp_client, token_joao, "transactions_get", {"transaction_id": mundo["parcela"]}))["code"] == "NOT_FOUND"
    assert err(call_tool(mcp_client, token_joao, "income_update", {"income_id": mundo["renda"], "amount": "1.00"}))["code"] == "NOT_FOUND"
    # A despesa dividida com ele, ele vê — com a parte dele.
    tx = ok(call_tool(mcp_client, token_joao, "transactions_get", {"transaction_id": mundo["tx"]}))["transaction"]
    assert tx["my_share"] == "388.88"
    # E não a edita (é da Alice; ele é `member`).
    assert err(call_tool(mcp_client, token_joao, "transactions_update", {"transaction_id": mundo["tx"], "title": "x"}))["code"] == "PERMISSION_DENIED"
