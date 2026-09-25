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
from app.models.attachment import Attachment
from app.models.estimate import MonthlyEstimate
from app.models.financing import AmortizationInstallment, Financing
from app.models.payment_account import PaymentAccount
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
    renda_fixa = ok(call_tool(mcp_client, c.token, "recurring_create", {
        "idempotency_key": str(uuid4()), "kind": "income", "title": SEGREDO, "amount": "4000.00", "materialize": "future",
    }))["recurring"]
    poupanca = PaymentAccount(name="Poupança", owner_user_id=c.alice.id, currency="BRL")
    db_session.add(poupanca)
    db_session.commit()
    transf = ok(call_tool(mcp_client, c.token, "transfers_create", {
        "idempotency_key": str(uuid4()), "from_account_id": c.conta.id, "to_account_id": poupanca.id, "amount": "50.00",
    }))
    anexo = Attachment(
        workspace_id=c.casa.id, transaction_id=avulsa["id"], filename=SEGREDO + ".png", content_type="image/png",
        size_bytes=12, data=b"\x89PNG\r\n\x1a\n0000", uploaded_by_user_id=c.alice.id,
    )
    financiamento = Financing(
        title=SEGREDO, total_amount="10000.00", interest_rate="0.01", start_date=c.hoje,
        installments_count=2, owner_user_id=c.alice.id,
    )
    db_session.add_all([anexo, financiamento])
    db_session.commit()
    for n in (1, 2):
        db_session.add(AmortizationInstallment(
            financing_id=financiamento.id, installment_number=n, due_date=c.hoje + timedelta(days=30 * n),
            principal_amount="5000.00", interest_amount="100.00", total_amount="5100.00",
            remaining_balance=str(10000 - 5000 * n) + ".00",
        ))
    db_session.commit()
    lote = ok(call_tool(mcp_client, c.token, "imports_commit", {
        "idempotency_key": str(uuid4()), "space_id": c.pessoal.id,
        "rows": [{"date": c.hoje.isoformat(), "title": SEGREDO + " importado", "amount": "12.34"}],
    }))
    estab = ok(call_tool(mcp_client, c.token, "categories_create", {
        "kind": "merchant", "name": SEGREDO + " Loja", "space_id": c.casa.id, "aliases": [SEGREDO + " apelido"],
    }))
    return {
        "c": c,
        "estab": estab["id"],
        "tx": avulsa["id"],
        "parcela": parcelada["id"],
        "grupo": parcelada["installment_group_id"],
        "renda": renda["id"],
        "acerto": acerto["id"],
        "recorrente": recorrente["id"],
        "renda_fixa": renda_fixa["id"],
        "transf": transf["id"],
        "anexo": anexo.id,
        "fin": financiamento.id,
        "lote": lote["batch_id"],
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
        "transactions_show": [{"transaction_id": m["tx"]}, {"transaction_id": m["parcela"]}],
        "statements_get": [{"card_id": c.nubank.id}],
        "statements_show": [{"card_id": c.nubank.id}],
        "reports_summary": [{"space_id": c.casa.id}],
        "reports_show": [{"space_id": c.casa.id}],
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
        "attachments_upload_link": [{"transaction_id": m["tx"]}, {"transaction_id": m["parcela"]}],
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
        "categories_create": [{"space_id": c.casa.id, "name": "Invasão"}, {"space_id": c.casa.id, "name": "x", "kind": "tag"}],
        "categories_update": [{"space_id": c.casa.id, "name": "Alimentação", "new_name": "Invasão"},
                              {"space_id": c.casa.id, "id": 1, "delete": True},
                              {"space_id": c.casa.id, "kind": "merchant", "id": m["estab"], "delete": True}],
        "transactions_history": [{"transaction_id": m["tx"]}, {"transaction_id": m["parcela"]}],
        "recurring_get": [{"recurring_id": m["recorrente"]}, {"recurring_id": m["renda_fixa"], "kind": "income"}],
        "recurring_delete": [{"recurring_id": m["recorrente"]}, {"recurring_id": m["renda_fixa"], "kind": "income"}],
        "income_list": [{"income_id": m["renda"]}],
        "income_delete": [{"income_id": m["renda"]}],
        "income_restore": [{"income_id": m["renda"]}],
        "accounts_statement": [{"account_id": c.conta.id}],
        "transfers_list": [{"account_id": c.conta.id}],
        "transfers_delete": [{"transfer_id": m["transf"]}],
        "statements_reopen": [{"card_id": c.nubank.id, "month": c.hoje.strftime("%Y-%m")}],
        "financings_list": [{"financing_id": m["fin"]}],
        "financings_installment": [{"action": "pay", "financing_id": m["fin"]}, {"action": "unpay", "financing_id": m["fin"]}],
        "attachments_get": [{"attachment_id": m["anexo"]}],
        "attachments_delete": [{"attachment_id": m["anexo"]}],
        "attachments_add": [{"transaction_id": m["tx"], "file": {"download_url": "https://files.oaiusercontent.com/x", "file_id": "f"}}],
        "imports_list": [{"batch_id": m["lote"]}],
        "imports_undo": [{"batch_id": m["lote"]}],
        "view_show": [{"view": "history", "transaction_id": m["tx"]}, {"view": "transactions", "space_id": c.casa.id},
                      {"view": "account", "account_id": c.conta.id}, {"view": "imports", "batch_id": m["lote"]},
                      {"view": "breakdown", "group_by": "person", "space_id": c.casa.id}],
        "reports_breakdown": [{"group_by": "category", "space_id": c.casa.id}, {"group_by": "card", "card_id": c.nubank.id},
                              {"group_by": "person", "person_id": c.alice.id}, {"group_by": "title", "import_batch_id": m["lote"]},
                              {"group_by": "merchant", "space_id": c.casa.id}],
    }


def _tem_id(nome: str) -> bool:
    props = input_schema(REGISTRY[nome]).get("properties", {})
    texto = str(props)
    return any(p.endswith("_id") or p.endswith("_ids") for p in props) or "_id'" in texto


def test_toda_tool_com_id_tem_caso_de_isolamento(db_session, mcp_client):
    get_server()
    com_id = {n for n in REGISTRY if _tem_id(n)}
    assert len(com_id) >= 25, com_id  # denominador: a varredura enxerga as tools
    chaves = ("tx", "parcela", "grupo", "renda", "acerto", "recorrente", "renda_fixa", "transf", "anexo", "fin", "lote", "estab")
    faltando = com_id - set(_casos({"c": _Falso(), **{k: 0 for k in chaves}}))
    assert not faltando, f"tools com id sem caso A×B: {sorted(faltando)}"


class _Falso:
    def __getattr__(self, nome):
        return self

    id = 0

    def isoformat(self):
        return "2026-01-01"

    def strftime(self, _):
        return "2026-01"


def test_bob_nao_alcanca_nada_da_alice(db_session, mcp_client, mundo, monkeypatch):
    from app.core.config import settings

    # A matriz passa de cem chamadas do Bob: o teto de uso é outro teste
    # (`test_audit_and_safety`), aqui ele só mascararia o que importa.
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
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
        assert nome in {"transactions_search", "debts_summary", "transactions_bulk_preview", "reports_breakdown"}, (
            nome, argumentos, saida)
        if nome == "transactions_search":
            assert saida["total_count"] == 0
        if nome == "reports_breakdown":
            assert saida["groups"] == [], (argumentos, saida)
        if nome == "transactions_bulk_preview":
            assert saida["count"] == 0 and saida["confirmation_token"] is None
    assert _fotografia(db_session) == antes, "o Bob alterou dados da Alice"


def _fotografia(db) -> dict:
    """Estado observável do que é da Alice — tem de sair idêntico."""
    from sqlmodel import select

    from app.models.account_ledger import AccountTransfer
    from app.models.category import Category
    from app.models.credit_card import StatementPayment
    from app.models.income import Income
    from app.models.recurring import RecurringIncome
    from app.models.settlement import Settlement
    from app.models.merchant import Merchant
    from app.models.tag import Tag
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
        "renda_ok": sorted((r.id, r.deleted_at is None) for r in db.exec(select(Income)).all()),
        "rendas_fixas": sorted((r.id, str(r.base_amount)) for r in db.exec(select(RecurringIncome)).all()),
        "transf": sorted((t.id, t.deleted_at is None) for t in db.exec(select(AccountTransfer)).all()),
        "anexos": sorted(a.id for a in db.exec(select(Attachment)).all()),
        "parcelas_fin": sorted((p.id, p.is_paid) for p in db.exec(select(AmortizationInstallment)).all()),
        "nomes_cat": sorted(cat.name for cat in db.exec(select(Category)).all()),
        "tags": len(db.exec(select(Tag)).all()),
        "estabs": sorted((e.id, e.name, tuple(e.aliases), e.deleted_at is None) for e in db.exec(select(Merchant)).all()),
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
