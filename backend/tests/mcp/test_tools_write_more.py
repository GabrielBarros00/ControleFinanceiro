"""Escritas fora de lançamentos: fatura, transferência, conciliação, renda, acertos,
planejamento e importação de extrato."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlmodel import select

from app.models.credit_card import StatementPayment
from app.models.import_batch import ImportBatch
from app.models.income import Income
from app.models.payment_account import PaymentAccount
from app.models.recurring import RecurringExpense
from app.models.settlement import Settlement
from app.models.transaction import Transaction
from app.services.oauth import scopes as escopos
from tests.mcp.conftest import call_tool, cookie_headers, err, issue_token, ok
from tests.mcp.scenario import cria_despesa, monta


@pytest.fixture
def c(db_session, mcp_client):
    return monta(db_session, mcp_client)


def chave() -> str:
    return str(uuid4())


# --- statements_pay ------------------------------------------------------------------

def test_paga_fatura_de_ciclo_encerrado_fechando_antes(mcp_client, db_session, c):
    # Compra de 45 dias atrás: a fatura dela já passou do fechamento (dia 3).
    cria_despesa(mcp_client, c.alice, c.pessoal, title="Mercado", amount="300.00",
                 day=c.hoje - timedelta(days=45), card=c.nubank)
    k = chave()
    saida = ok(call_tool(mcp_client, c.token, "statements_pay", {"idempotency_key": k, "account": "Itaú"}))
    assert saida["closed_now"] is True
    assert saida["amount_paid"] == "300.00" and saida["balance"] == "0.00" and saida["status"] == "paid"
    assert saida["account"]["name"] == "Itaú"
    # Retry com a mesma chave: não paga de novo.
    de_novo = ok(call_tool(mcp_client, c.token, "statements_pay", {"idempotency_key": k, "account": "Itaú"}))
    assert de_novo["replayed"] is True
    assert len(db_session.exec(select(StatementPayment)).all()) == 1


def test_pagamento_parcial_e_acima_do_saldo(mcp_client, db_session, c):
    cria_despesa(mcp_client, c.alice, c.pessoal, title="Mercado", amount="300.00",
                 day=c.hoje - timedelta(days=45), card=c.nubank)
    parcial = ok(call_tool(mcp_client, c.token, "statements_pay", {"idempotency_key": chave(), "amount": "100.00"}))
    assert parcial["balance"] == "200.00" and parcial["status"] == "closed"
    erro = err(call_tool(mcp_client, c.token, "statements_pay", {
        "idempotency_key": chave(), "month": parcial["month"], "amount": "500.00",
    }))
    assert erro["code"] == "CONFLICT"


def test_fatura_em_curso_nao_e_paga(mcp_client, c):
    cria_despesa(mcp_client, c.alice, c.pessoal, title="Café", amount="8.00", day=c.hoje, card=c.nubank)
    mes = ok(call_tool(mcp_client, c.token, "cards_list"))["cards"][0]["current_statement"]["month"]
    erro = err(call_tool(mcp_client, c.token, "statements_pay", {"idempotency_key": chave(), "month": mes}))
    assert erro["code"] == "BUSINESS_RULE_VIOLATION" and "em curso" in erro["message"]


def test_pagar_fatura_exige_escopo_de_contas(mcp_client, db_session, c):
    token = issue_token(db_session, c.alice, [escopos.FINANCE_READ, escopos.TRANSACTIONS_WRITE])
    erro = err(call_tool(mcp_client, token, "statements_pay", {"idempotency_key": chave()}))
    assert erro["code"] == "PERMISSION_DENIED" and erro["required_scopes"] == ["accounts.write"]


def test_bob_nao_paga_fatura_da_alice(mcp_client, db_session, c):
    cria_despesa(mcp_client, c.alice, c.pessoal, title="Mercado", amount="300.00",
                 day=c.hoje - timedelta(days=45), card=c.nubank)
    erro = err(call_tool(mcp_client, c.token_bob, "statements_pay", {"idempotency_key": chave(), "card_id": c.nubank.id}))
    assert erro["code"] == "NOT_FOUND"
    assert db_session.exec(select(StatementPayment)).all() == []


# --- transfers_create / accounts_adjust_balance -----------------------------------------

def test_transferencia_entre_contas(mcp_client, db_session, c):
    db_session.add(PaymentAccount(name="Poupança", owner_user_id=c.alice.id, currency="BRL"))
    db_session.commit()
    k = chave()
    saida = ok(call_tool(mcp_client, c.token, "transfers_create", {
        "idempotency_key": k, "from_account": "itau", "to_account": "poupança", "amount": "500.00",
    }))
    assert saida["from_account"]["name"] == "Itaú" and saida["to_account"]["name"] == "Poupança"
    assert saida["to_amount"] == "500.00"
    assert ok(call_tool(mcp_client, c.token, "transfers_create", {
        "idempotency_key": k, "from_account": "itau", "to_account": "poupança", "amount": "500.00",
    }))["replayed"] is True


def test_transferir_para_conta_alheia_nao_encontra(mcp_client, db_session, c):
    conta_bob = PaymentAccount(name="Conta do Bob", owner_user_id=c.bob.id, currency="BRL")
    db_session.add(conta_bob)
    db_session.commit()
    erro = err(call_tool(mcp_client, c.token, "transfers_create", {
        "idempotency_key": chave(), "from_account": "Itaú", "to_account_id": conta_bob.id, "amount": "10.00",
    }))
    assert erro["code"] == "NOT_FOUND"


def test_conciliacao_de_saldo(mcp_client, db_session, c):
    erro = err(call_tool(mcp_client, c.token, "accounts_adjust_balance", {
        "idempotency_key": chave(), "account": "Itaú", "real_balance": "900.00",
    }))
    assert erro["code"] == "CONFLICT"  # sem saldo inicial não há diferença a calcular
    r = mcp_client.put(f"/api/v1/me/payment-accounts/{c.conta.id}/opening-balance",
                       json={"amount": "1000.00", "as_of": (c.hoje - timedelta(days=10)).isoformat()},
                       headers=cookie_headers(c.alice))
    assert r.status_code == 200, r.text
    saida = ok(call_tool(mcp_client, c.token, "accounts_adjust_balance", {
        "idempotency_key": chave(), "account": "Itaú", "real_balance": "900.00", "note": "tarifa",
    }))
    assert saida["previous_balance"] == "1000.00" and saida["new_balance"] == "900.00"
    assert saida["adjustment"] == "-100.00"


# --- income ----------------------------------------------------------------------------

def test_renda_criar_receber_e_cancelar(mcp_client, db_session, c):
    futura = (c.hoje + timedelta(days=5)).isoformat()
    renda = ok(call_tool(mcp_client, c.token, "income_create", {
        "idempotency_key": chave(), "title": "Freela", "amount": "800.00", "date": futura,
    }))["income"]
    assert renda["status"] == "expected"
    recebida = ok(call_tool(mcp_client, c.token, "income_update", {
        "income_id": renda["id"], "status": "received", "account": "Itaú",
    }))
    assert recebida["income"]["status"] == "received" and recebida["previous"]["status"] == "expected"
    assert recebida["income"]["account_id"] == c.conta.id
    cancelada = ok(call_tool(mcp_client, c.token, "income_update", {"income_id": renda["id"], "status": "cancelled"}))
    assert cancelada["income"]["status"] == "cancelled"


def test_renda_de_outra_pessoa_nao_existe(mcp_client, db_session, c):
    renda = ok(call_tool(mcp_client, c.token, "income_create", {
        "idempotency_key": chave(), "title": "Salário", "amount": "5000.00",
    }))["income"]
    erro = err(call_tool(mcp_client, c.token_bob, "income_update", {"income_id": renda["id"], "amount": "1.00"}))
    assert erro["code"] == "NOT_FOUND"
    db_session.expire_all()
    assert db_session.get(Income, renda["id"]).amount == Decimal("5000.00")


def test_renda_idempotente(mcp_client, db_session, c):
    args = {"idempotency_key": chave(), "title": "Salário", "amount": "5000.00"}
    ok(call_tool(mcp_client, c.token, "income_create", args))
    assert ok(call_tool(mcp_client, c.token, "income_create", args))["replayed"] is True
    assert len(db_session.exec(select(Income)).all()) == 1


# --- settlements ------------------------------------------------------------------------

def test_joao_me_pagou(mcp_client, db_session, c):
    cria_despesa(mcp_client, c.alice, c.casa, title="Jantar", amount="90.00", day=c.hoje, split_with=[c.joao])
    saida = ok(call_tool(mcp_client, c.token, "settlements_create", {
        "idempotency_key": chave(), "person": "João", "direction": "they_paid_me", "amount": "45.00",
    }))
    assert saida["payer"]["name"] == "João Pereira" and saida["space"]["name"] == "Casa"
    dividas = ok(call_tool(mcp_client, c.token, "debts_summary", {"person": "João"}))
    assert dividas["to_receive"] == "0.00"


def test_acerto_acima_da_divida_e_recusado(mcp_client, db_session, c):
    cria_despesa(mcp_client, c.alice, c.casa, title="Jantar", amount="90.00", day=c.hoje, split_with=[c.joao])
    erro = err(call_tool(mcp_client, c.token, "settlements_create", {
        "idempotency_key": chave(), "person": "João", "direction": "they_paid_me", "amount": "100.00",
    }))
    assert erro["code"] == "BUSINESS_RULE_VIOLATION"
    assert db_session.exec(select(Settlement)).all() == []


def test_member_so_registra_acerto_em_que_pagou(mcp_client, db_session, c):
    cria_despesa(mcp_client, c.joao, c.casa, title="Gás", amount="100.00", day=c.hoje, split_with=[c.alice])
    token_joao = issue_token(db_session, c.joao)
    # Alice deve 50 ao João; João (member) não pode afirmar que a Alice pagou.
    erro = err(call_tool(mcp_client, token_joao, "settlements_create", {
        "idempotency_key": chave(), "person": "Alice", "direction": "they_paid_me", "amount": "50.00",
    }))
    assert erro["code"] == "PERMISSION_DENIED"


def test_desfazer_acerto(mcp_client, db_session, c):
    cria_despesa(mcp_client, c.alice, c.casa, title="Jantar", amount="90.00", day=c.hoje, split_with=[c.joao])
    acerto = ok(call_tool(mcp_client, c.token, "settlements_create", {
        "idempotency_key": chave(), "person": "João", "direction": "they_paid_me", "amount": "45.00",
    }))
    assert err(call_tool(mcp_client, c.token_bob, "settlements_delete", {"settlement_id": acerto["id"]}))["code"] == "NOT_FOUND"
    ok(call_tool(mcp_client, c.token, "settlements_delete", {"settlement_id": acerto["id"]}))
    assert ok(call_tool(mcp_client, c.token, "debts_summary", {"person": "João"}))["to_receive"] == "45.00"


# --- planejamento -----------------------------------------------------------------------

def test_recorrencia_criar_editar_pausar(mcp_client, db_session, c):
    criada = ok(call_tool(mcp_client, c.token, "recurring_create", {
        "idempotency_key": chave(), "title": "Streaming", "amount": "49.90", "card": "Nubank",
        "day_of_month": 12, "materialize": "future",
    }))["recurring"]
    assert criada["space"]["name"] == "Meu espaço" and criada["card_id"] == c.nubank.id
    editada = ok(call_tool(mcp_client, c.token, "recurring_update", {"recurring_id": criada["id"], "amount": "55.00"}))
    assert editada["recurring"]["amount"] == "55.00" and "amount" in editada["changed"]
    pausada = ok(call_tool(mcp_client, c.token, "recurring_update", {"recurring_id": criada["id"], "active": False}))
    assert pausada["recurring"]["active"] is False


def test_recorrencia_dividida_e_de_outro_espaco(mcp_client, db_session, c):
    criada = ok(call_tool(mcp_client, c.token, "recurring_create", {
        "idempotency_key": chave(), "title": "Aluguel", "amount": "2000.00", "day_of_month": 5,
        "split_with": ["João"], "payment_method": "pix", "materialize": "future",
    }))["recurring"]
    assert criada["space"]["name"] == "Casa"
    t = db_session.get(RecurringExpense, criada["id"])
    assert {s["user_id"] for s in t.split_snapshot} == {c.alice.id, c.joao.id}
    assert err(call_tool(mcp_client, c.token_bob, "recurring_update", {"recurring_id": criada["id"], "amount": "1.00"}))["code"] == "NOT_FOUND"


def test_meta_do_mes(mcp_client, c):
    primeira = ok(call_tool(mcp_client, c.token, "budgets_set", {
        "space": "Meu espaço", "category": "Alimentação", "amount": "800.00",
    }))
    assert primeira["created"] is True and primeira["scope"] == "space"
    segunda = ok(call_tool(mcp_client, c.token, "budgets_set", {
        "space": "Meu espaço", "category": "Alimentação", "amount": "900.00",
    }))
    assert segunda["created"] is False and segunda["id"] == primeira["id"] and segunda["amount"] == "900.00"
    erro = err(call_tool(mcp_client, c.token, "budgets_set", {"space": "Casa", "category": "Alimentação", "amount": "500"}))
    assert erro["code"] == "VALIDATION_ERROR"  # espaço compartilhado: pessoal ou da casa?
    pessoal = ok(call_tool(mcp_client, c.token, "budgets_set", {
        "space": "Casa", "category": "Alimentação", "amount": "500", "scope": "personal",
    }))
    assert pessoal["scope"] == "personal"


def test_categoria_nova_e_duplicada(mcp_client, c):
    nova = ok(call_tool(mcp_client, c.token, "categories_create", {"space": "Casa", "name": "Pets"}))
    assert nova["name"] == "Pets"
    erro = err(call_tool(mcp_client, c.token, "categories_create", {"space": "Casa", "name": "alimentacao"}))
    assert erro["code"] == "ALREADY_EXISTS" and erro["details"]["name"] == "Alimentação"


# --- importação de extrato --------------------------------------------------------------

def test_conferir_e_importar_extrato(mcp_client, db_session, c):
    ontem = c.hoje - timedelta(days=1)
    cria_despesa(mcp_client, c.alice, c.pessoal, title="Padaria", amount="12.50", day=ontem)
    linhas = [
        {"line": 1, "date": ontem.isoformat(), "title": "Padaria", "amount": "12.50"},
        {"line": 2, "date": ontem.isoformat(), "title": "POSTO SHELL", "amount": "150.00"},
    ]
    previa = ok(call_tool(mcp_client, c.token, "imports_preview", {"space": "Meu espaço", "rows": linhas}))
    assert [r["possible_duplicate"] for r in previa["rows"]] == [True, False]
    assert previa["new_count"] == 1

    decididas = [{**linhas[0], "decision": "ignore"}, linhas[1]]
    k = chave()
    feito = ok(call_tool(mcp_client, c.token, "imports_commit", {"idempotency_key": k, "space": "Meu espaço", "rows": decididas}))
    assert feito["imported"] == 1 and feito["ignored"] == 1 and len(feito["transaction_ids"]) == 1
    tx = db_session.get(Transaction, feito["transaction_ids"][0])
    assert tx.title == "POSTO SHELL" and tx.settled_at is not None

    # Mesma chave: replay. Chave nova com as mesmas linhas: o fingerprint pula a já importada.
    assert ok(call_tool(mcp_client, c.token, "imports_commit", {"idempotency_key": k, "space": "Meu espaço", "rows": decididas}))["replayed"] is True
    outra = ok(call_tool(mcp_client, c.token, "imports_commit", {"idempotency_key": chave(), "space": "Meu espaço", "rows": [linhas[1]]}))
    assert outra["imported"] == 0 and outra["duplicate"] == 1
    previa = ok(call_tool(mcp_client, c.token, "imports_preview", {"space": "Meu espaço", "rows": [linhas[1]]}))
    assert previa["rows"][0]["already_imported"] is True
    assert len(db_session.exec(select(ImportBatch)).all()) == 2


def test_importar_em_espaco_alheio(mcp_client, c):
    erro = err(call_tool(mcp_client, c.token, "imports_commit", {
        "idempotency_key": chave(), "space_id": c.ws_bob.id,
        "rows": [{"date": c.hoje.isoformat(), "title": "X", "amount": "1.00"}],
    }))
    assert erro["code"] == "NOT_FOUND"


def test_acerto_de_outros_dois_e_invisivel_para_terceiro_membro(mcp_client, db_session, c):
    from app.models.workspace import WorkspaceMembership, WorkspaceRole
    from tests.mcp.conftest import make_user

    carla = make_user(db_session, "Carla Dias", "carla@example.com")
    db_session.add(WorkspaceMembership(workspace_id=c.casa.id, user_id=carla.id, role=WorkspaceRole.member))
    db_session.commit()
    cria_despesa(mcp_client, c.alice, c.casa, title="Jantar", amount="90.00", day=c.hoje, split_with=[c.joao])
    acerto = ok(call_tool(mcp_client, c.token, "settlements_create", {
        "idempotency_key": chave(), "person": "João", "direction": "they_paid_me", "amount": "45.00",
    }))
    token_carla = issue_token(db_session, carla)
    # Carla é `member` sem visão da casa inteira: o acerto de Alice e João não existe para ela
    # (NOT_FOUND, e não "sem permissão" — nem a existência vaza).
    assert err(call_tool(mcp_client, token_carla, "settlements_delete", {"settlement_id": acerto["id"]}))["code"] == "NOT_FOUND"
    db_session.expire_all()
    assert db_session.get(Settlement, acerto["id"]).deleted_at is None


def test_renda_convertida_valor_novo_e_na_moeda_original(mcp_client, db_session, c, monkeypatch):
    """Mesma regra da despesa: numa renda de US$ 1.000, `amount: 1200` são US$ 1.200 (reconvertidos)."""
    from app.services.exchange_rate_store import ExchangeRateStore

    monkeypatch.setattr(ExchangeRateStore, "rate_between", classmethod(lambda cls, *a, **k: (Decimal("5.00"), "ptax")))
    renda = ok(call_tool(mcp_client, c.token, "income_create", {
        "idempotency_key": chave(), "title": "Consultoria", "amount": "1000.00", "currency": "usd",
    }))["income"]
    assert renda["amount"] == "5000.00" and renda["original_currency"] == "USD"
    nova = ok(call_tool(mcp_client, c.token, "income_update", {"income_id": renda["id"], "amount": "1200.00"}))["income"]
    assert nova["amount"] == "6000.00"
    assert nova["original_amount"] == "1200.00" and nova["original_currency"] == "USD"
