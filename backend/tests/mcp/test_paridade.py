"""Paridade MCP × app: as lacunas do relatório de auditoria do ChatGPT, fechadas.

Cada teste é uma pergunta que o agente não conseguia responder (ou uma correção
que não conseguia desfazer) e agora consegue, pelas mesmas regras do app.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlmodel import select

from app.models.account_ledger import AccountTransfer
from app.models.attachment import Attachment
from app.models.credit_card import StatementPayment
from app.models.financing import AmortizationInstallment, Financing
from app.models.income import Income
from app.models.payment_account import PaymentAccount
from app.models.recurring import RecurringIncome
from app.models.tag import Tag, TransactionTagLink
from app.models.transaction import Transaction, TransactionStatus
from app.services import remote_file
from tests.mcp.conftest import call_tool, cookie_headers, err, issue_token, ok
from tests.mcp.scenario import cria_despesa, monta

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture
def c(db_session, mcp_client):
    return monta(db_session, mcp_client)


def chave() -> str:
    return str(uuid4())


def _cria(mcp_client, c, **args) -> dict:
    return ok(call_tool(mcp_client, c.token, "transactions_create", {"idempotency_key": chave(), **args}))["transaction"]


# --- recorrência: leitura completa, renda recorrente, exclusão ------------------------------

def test_assinatura_dividida_mostra_a_minha_parte(mcp_client, c):
    """O caso do relatório: R$ 53,90 dividido em dois — a recorrência mostrava só o cheio."""
    criada = ok(call_tool(mcp_client, c.token, "recurring_create", {
        "idempotency_key": chave(), "title": "Streaming", "amount": "53.90", "space": "Casa",
        "split_with": ["João"], "card": "Nubank", "day_of_month": 12, "materialize": "future",
    }))["recurring"]
    assert criada["my_share"] == "26.95"
    assert {p["person"]["name"]: p["amount"] for p in criada["split"]} == {"Alice Souza": "26.95", "João Pereira": "26.95"}
    assert criada["card"]["name"] == "Nubank" and criada["next_occurrence"] is not None

    detalhe = ok(call_tool(mcp_client, c.token, "recurring_get", {"recurring_id": criada["id"]}))
    assert detalhe["recurring"]["paid_by"]["name"] == "Alice Souza"
    assert len(detalhe["upcoming"]) == 6 and detalhe["upcoming"][0] == criada["next_occurrence"]

    lista = ok(call_tool(mcp_client, c.token, "recurring_list", {"kind": "expense"}))
    assert lista["monthly_my_share"] == {"BRL": "26.95"}


def test_renda_recorrente_pelo_agente(mcp_client, db_session, c):
    criada = ok(call_tool(mcp_client, c.token, "recurring_create", {
        "idempotency_key": chave(), "kind": "income", "title": "Salário", "amount": "4000.00",
        "day_of_month": 5, "account": "Itaú", "materialize": "future",
    }))["recurring"]
    assert criada["kind"] == "income" and criada["account"]["name"] == "Itaú" and criada["my_share"] == "4000.00"

    subiu = ok(call_tool(mcp_client, c.token, "recurring_update", {
        "recurring_id": criada["id"], "kind": "income", "amount": "4500.00", "expected_version": criada["version"],
    }))
    assert subiu["recurring"]["amount"] == "4500.00" and "amount" in subiu["changed"]
    velha = err(call_tool(mcp_client, c.token, "recurring_update", {
        "recurring_id": criada["id"], "kind": "income", "active": False, "expected_version": criada["version"],
    }))
    assert velha["code"] == "CONFLICT"

    # Renda é pessoal: campo de despesa é recusado com explicação.
    erro = err(call_tool(mcp_client, c.token, "recurring_create", {
        "idempotency_key": chave(), "kind": "income", "title": "x", "amount": "1.00", "split_with": ["João"],
    }))
    assert erro["code"] == "VALIDATION_ERROR" and "split_with" in erro["message"]

    ok(call_tool(mcp_client, c.token, "recurring_delete", {"recurring_id": criada["id"], "kind": "income"}))
    assert db_session.get(RecurringIncome, criada["id"]) is None


def test_excluir_recorrencia_cancelando_o_que_esta_em_aberto(mcp_client, db_session, c):
    criada = ok(call_tool(mcp_client, c.token, "recurring_create", {
        "idempotency_key": chave(), "title": "Academia", "amount": "99.00", "payment_method": "pix",
        "day_of_month": 28, "materialize": "current",
    }))["recurring"]
    geradas = db_session.exec(select(Transaction).where(Transaction.recurring_expense_id == criada["id"])).all()
    feito = ok(call_tool(mcp_client, c.token, "recurring_delete", {
        "recurring_id": criada["id"], "cancel_open_occurrences": True,
    }))
    abertas = [t.id for t in geradas if t.settled_at is None]
    assert sorted(feito["cancelled_occurrences"]) == sorted(abertas)
    for t in geradas:
        db_session.refresh(t)
        assert t.recurring_expense_id is None
        assert (t.status == TransactionStatus.cancelled) == (t.id in abertas)


# --- renda: todos os campos, excluir e restaurar --------------------------------------------

def test_renda_com_descricao_conta_excluir_e_restaurar(mcp_client, db_session, c):
    renda = ok(call_tool(mcp_client, c.token, "income_create", {
        "idempotency_key": chave(), "title": "Freela", "amount": "800.00", "description": "site da padaria", "account": "Itaú",
    }))["income"]
    lida = ok(call_tool(mcp_client, c.token, "income_list", {"income_id": renda["id"]}))["incomes"][0]
    assert lida["description"] == "site da padaria" and lida["account"]["name"] == "Itaú" and lida["version"] == renda["version"]

    ok(call_tool(mcp_client, c.token, "income_delete", {"income_id": renda["id"]}))
    assert db_session.get(Income, renda["id"]).deleted_at is not None
    assert err(call_tool(mcp_client, c.token, "income_list", {"income_id": renda["id"]}))["code"] == "NOT_FOUND"
    volta = ok(call_tool(mcp_client, c.token, "income_restore", {"income_id": renda["id"]}))["income"]
    assert volta["amount"] == "800.00"
    db_session.expire_all()
    assert db_session.get(Income, renda["id"]).deleted_at is None
    # Outra pessoa não restaura (nem descobre que existe).
    assert err(call_tool(mcp_client, c.token_bob, "income_restore", {"income_id": renda["id"]}))["code"] == "NOT_FOUND"


# --- extrato e transferências ----------------------------------------------------------------

def test_extrato_da_conta_explica_o_saldo(mcp_client, db_session, c):
    poupanca = PaymentAccount(name="Poupança", owner_user_id=c.alice.id, currency="BRL")
    db_session.add(poupanca)
    db_session.commit()
    r = mcp_client.put(f"/api/v1/me/payment-accounts/{c.conta.id}/opening-balance",
                       json={"amount": "1000.00", "as_of": (c.hoje - timedelta(days=10)).isoformat()},
                       headers=cookie_headers(c.alice))
    assert r.status_code == 200, r.text
    _cria(mcp_client, c, title="Farmácia", amount="40.00", payment_method="pix", account="Itaú",
          date=(c.hoje - timedelta(days=2)).isoformat())
    transf = ok(call_tool(mcp_client, c.token, "transfers_create", {
        "idempotency_key": chave(), "from_account": "Itaú", "to_account": "Poupança", "amount": "300.00",
    }))
    extrato = ok(call_tool(mcp_client, c.token, "accounts_statement", {"account": "Itaú"}))
    assert extrato["mode"] == "account" and extrato["balance"] == "660.00"
    # Mais recente primeiro, e o saldo corrente fecha: 1000 − 40 − 300.
    assert [e["amount"] for e in extrato["entries"]][:2] == ["-300.00", "-40.00"]
    assert extrato["entries"][0]["running_balance"] == "660.00"

    lista = ok(call_tool(mcp_client, c.token, "transfers_list", {"account": "Poupança"}))["transfers"]
    assert [t["id"] for t in lista] == [transf["id"]]
    ok(call_tool(mcp_client, c.token, "transfers_delete", {"transfer_id": transf["id"]}))
    assert db_session.get(AccountTransfer, transf["id"]).deleted_at is not None
    depois = ok(call_tool(mcp_client, c.token, "accounts_statement", {"account": "Itaú"}))
    assert depois["balance"] == "960.00"


def test_caixa_do_mes_sem_conta(mcp_client, c):
    _cria(mcp_client, c, title="Padaria", amount="12.00", payment_method="cash")
    caixa = ok(call_tool(mcp_client, c.token, "accounts_statement", {}))
    assert caixa["mode"] == "cash" and Decimal(caixa["cash_out"]) >= Decimal("12.00")
    assert any(e["title"] == "Padaria" and e["amount"] == "-12.00" for e in caixa["entries"])


# --- fatura: pagamentos e estorno --------------------------------------------------------------

def test_pagamento_de_fatura_aparece_e_se_estorna(mcp_client, db_session, c):
    cria_despesa(mcp_client, c.alice, c.pessoal, title="Mercado", amount="300.00",
                 day=c.hoje - timedelta(days=45), card=c.nubank)
    pago = ok(call_tool(mcp_client, c.token, "statements_pay", {"idempotency_key": chave(), "account": "Itaú"}))
    fatura = ok(call_tool(mcp_client, c.token, "statements_get", {"month": pago["month"]}))
    assert [(p["amount"], p["account"]["name"]) for p in fatura["payments"]] == [("300.00", "Itaú")]

    estorno = ok(call_tool(mcp_client, c.token, "statements_reopen", {"month": pago["month"]}))
    assert estorno["previous_status"] == "paid" and estorno["status"] == "closed"
    assert [p["amount"] for p in estorno["reversed_payments"]] == ["300.00"] and estorno["balance"] == "300.00"
    assert all(p.deleted_at is not None for p in db_session.exec(select(StatementPayment)).all())
    # Retry: sem pagamento a estornar, nada anda (a fatura NÃO vira "aberta").
    de_novo = ok(call_tool(mcp_client, c.token, "statements_reopen", {"month": pago["month"]}))
    assert de_novo["status"] == "closed" and de_novo["reversed_payments"] == []


# --- financiamento ---------------------------------------------------------------------------

def _financiamento(db, c) -> Financing:
    f = Financing(title="Carro", total_amount="10000.00", interest_rate="0.01", start_date=c.hoje,
                  installments_count=2, owner_user_id=c.alice.id)
    db.add(f)
    db.commit()
    for n in (1, 2):
        db.add(AmortizationInstallment(
            financing_id=f.id, installment_number=n, due_date=c.hoje + timedelta(days=30 * n),
            principal_amount="5000.00", interest_amount="100.00", total_amount="5100.00",
            remaining_balance=f"{10000 - 5000 * n}.00",
        ))
    db.commit()
    return f


def test_financiamento_ler_pagar_e_desfazer(mcp_client, db_session, c):
    f = _financiamento(db_session, c)
    lido = ok(call_tool(mcp_client, c.token, "financings_list", {"financing": "Carro"}))
    assert lido["financings"][0]["outstanding"] == "10000.00" and len(lido["schedule"]) == 2
    pago = ok(call_tool(mcp_client, c.token, "financings_installment", {"action": "pay", "account": "Itaú", "space": "Casa"}))
    assert pago["installment"] == 1 and pago["financing"]["outstanding"] == "5000.00"
    tx = db_session.get(Transaction, pago["transaction_id"])
    assert tx.workspace_id == c.casa.id and tx.total_amount == Decimal("5100.00")
    desfeito = ok(call_tool(mcp_client, c.token, "financings_installment", {"action": "unpay", "financing_id": f.id}))
    assert desfeito["installment"] == 1 and desfeito["financing"]["outstanding"] == "10000.00"
    db_session.refresh(tx)
    assert tx.deleted_at is not None
    assert all(not p.is_paid for p in db_session.exec(select(AmortizationInstallment)).all())


# --- anexos ------------------------------------------------------------------------------------

def _anexo(db, c, tx_id, *, ws=None, dono=None) -> Attachment:
    a = Attachment(workspace_id=ws or c.pessoal.id, transaction_id=tx_id, filename="recibo.png",
                   content_type="image/png", size_bytes=len(PNG), data=PNG, uploaded_by_user_id=(dono or c.alice).id)
    db.add(a)
    db.commit()
    return a


def test_ler_e_apagar_anexo(mcp_client, db_session, c):
    tx = _cria(mcp_client, c, title="Mercado", amount="80.00")
    a = _anexo(db_session, c, tx["id"])
    lido = ok(call_tool(mcp_client, c.token, "transactions_get", {"transaction_id": tx["id"]}))["transaction"]
    assert [f["filename"] for f in lido["files"]] == ["recibo.png"]
    resultado = call_tool(mcp_client, c.token, "attachments_get", {"attachment_id": a.id})
    assert resultado["structuredContent"]["delivered"] is True
    imagem = [b for b in resultado["content"] if b["type"] == "image"]
    assert imagem and imagem[0]["mimeType"] == "image/png"
    ok(call_tool(mcp_client, c.token, "attachments_delete", {"attachment_id": a.id}))
    assert db_session.get(Attachment, a.id) is None


def test_anexo_grande_nao_vai_para_o_modelo(mcp_client, db_session, c, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "MCP_ATTACHMENT_TO_MODEL_MAX_BYTES", 10)
    tx = _cria(mcp_client, c, title="Mercado", amount="80.00")
    a = _anexo(db_session, c, tx["id"])
    resultado = call_tool(mcp_client, c.token, "attachments_get", {"attachment_id": a.id})
    assert resultado["structuredContent"]["delivered"] is False
    assert all(b["type"] == "text" for b in resultado["content"])


def test_anexo_de_outro_membro_member_nao_apaga(mcp_client, db_session, c):
    tx = cria_despesa(mcp_client, c.alice, c.casa, title="Mercado", amount="80.00", day=c.hoje, split_with=[c.joao])
    a = _anexo(db_session, c, tx["id"], ws=c.casa.id)
    token_joao = issue_token(db_session, c.joao)
    erro = err(call_tool(mcp_client, token_joao, "attachments_delete", {"attachment_id": a.id}))
    assert erro["code"] == "PERMISSION_DENIED"


def test_anexar_arquivo_da_conversa_do_chatgpt(mcp_client, db_session, c, monkeypatch):
    tx = _cria(mcp_client, c, title="Mercado", amount="80.00")
    chamadas = []

    def falso(url, *, allowed_hosts, max_bytes, **_):
        chamadas.append((url, list(allowed_hosts), max_bytes))
        return PNG, "image/png"

    monkeypatch.setattr("app.mcp.tools.attachments.fetch_file", falso)
    feito = ok(call_tool(mcp_client, c.token, "attachments_add", {
        "transaction_id": tx["id"],
        "file": {"download_url": "https://files.oaiusercontent.com/file-abc", "file_id": "file-abc", "file_name": "nota.png"},
    }))
    assert feito["attachment"]["filename"] == "nota.png" and chamadas[0][1] == ["oaiusercontent.com"]
    anexo = db_session.get(Attachment, feito["attachment"]["id"])
    assert anexo.size_bytes == len(PNG) and anexo.uploaded_by_user_id == c.alice.id


def test_arquivo_da_conversa_so_de_host_permitido():
    with pytest.raises(remote_file.RemoteFileError, match="não vem do app de chat"):
        remote_file.fetch_file("https://evil.example.com/x.png", allowed_hosts=["oaiusercontent.com"], max_bytes=100)
    with pytest.raises(remote_file.RemoteFileError, match="desligado"):
        remote_file.fetch_file("https://files.oaiusercontent.com/x", allowed_hosts=[], max_bytes=100)
    with pytest.raises(remote_file.RemoteFileError, match="https"):
        remote_file.fetch_file("http://files.oaiusercontent.com/x", allowed_hosts=["oaiusercontent.com"], max_bytes=100)
    # Nome permitido que resolve para IP interno (DNS rebinding) também não passa.
    with pytest.raises(remote_file.RemoteFileError, match="não é público"):
        remote_file.fetch_file("https://files.oaiusercontent.com/x", allowed_hosts=["oaiusercontent.com"], max_bytes=100,
                               resolver=lambda host: ["10.0.0.5"])
    assert remote_file.host_permitido("files.oaiusercontent.com", ["oaiusercontent.com"])
    assert not remote_file.host_permitido("oaiusercontent.com.evil.com", ["oaiusercontent.com"])


# --- categorias e tags ---------------------------------------------------------------------------

def test_criar_renomear_e_excluir_tag_e_categoria(mcp_client, db_session, c):
    tag = ok(call_tool(mcp_client, c.token, "categories_create", {"kind": "tag", "name": "Trabalho", "space": "Casa"}))
    assert tag["kind"] == "tag"
    dup = err(call_tool(mcp_client, c.token, "categories_create", {"kind": "tag", "name": "trabalho", "space": "Casa"}))
    assert dup["code"] == "ALREADY_EXISTS"
    ren = ok(call_tool(mcp_client, c.token, "categories_update", {"space": "Casa", "name": "Alimentação", "new_name": "Alimentação fora"}))
    assert ren["previous_name"] == "Alimentação" and ren["name"] == "Alimentação fora"
    tx = cria_despesa(mcp_client, c.alice, c.casa, title="Almoço", amount="30.00", day=c.hoje)
    ok(call_tool(mcp_client, c.token, "transactions_update", {"transaction_id": tx["id"], "tags": ["Trabalho"]}))
    ok(call_tool(mcp_client, c.token, "categories_update", {"space": "Casa", "kind": "tag", "name": "Trabalho", "delete": True}))
    assert db_session.get(Tag, tag["id"]).deleted_at is not None
    assert db_session.exec(select(TransactionTagLink).where(TransactionTagLink.tag_id == tag["id"])).all() == []


# --- agrupamento --------------------------------------------------------------------------------

def test_quanto_gastei_em_cada_estabelecimento(mcp_client, c):
    for titulo, valor in (("Mercado Lela", "100.00"), ("MERCADO LELA", "50.00"), ("iFood", "40.00")):
        _cria(mcp_client, c, title=titulo, amount=valor, category="Mercado" if "ela" in titulo.lower() else "Alimentação")
    por_titulo = ok(call_tool(mcp_client, c.token, "reports_breakdown", {"group_by": "title"}))
    assert [(g["name"], g["amount"], g["count"]) for g in por_titulo["groups"]] == [
        ("Mercado Lela", "150.00", 2), ("iFood", "40.00", 1),
    ]
    assert por_titulo["totals"] == {"BRL": "190.00"}
    por_cat = ok(call_tool(mcp_client, c.token, "reports_breakdown", {"group_by": "category"}))
    assert {g["name"]: g["amount"] for g in por_cat["groups"]} == {"Mercado": "150.00", "Alimentação": "40.00"}


def test_agrupar_por_pessoa_e_sua_parte(mcp_client, c):
    cria_despesa(mcp_client, c.alice, c.casa, title="Jantar", amount="100.00", day=c.hoje, split_with=[c.joao])
    pessoa = ok(call_tool(mcp_client, c.token, "reports_breakdown", {"group_by": "person", "space": "Casa"}))
    assert {g["name"]: g["amount"] for g in pessoa["groups"]} == {"Alice Souza": "50.00", "João Pereira": "50.00"}
    minha = ok(call_tool(mcp_client, c.token, "reports_breakdown", {"group_by": "space"}))
    cheia = ok(call_tool(mcp_client, c.token, "reports_breakdown", {"group_by": "space", "basis": "total"}))
    assert minha["totals"] == {"BRL": "50.00"} and cheia["totals"] == {"BRL": "100.00"}


# --- importações: listar e desfazer --------------------------------------------------------------

def test_desfazer_importacao_pela_previa(mcp_client, db_session, c):
    lote = ok(call_tool(mcp_client, c.token, "imports_commit", {
        "idempotency_key": chave(), "space": "Casa",
        "rows": [{"date": c.hoje.isoformat(), "title": "Uber", "amount": "23.00"},
                 {"date": c.hoje.isoformat(), "title": "Padaria", "amount": "9.50"}],
    }))
    lotes = ok(call_tool(mcp_client, c.token, "imports_list", {}))["batches"]
    assert lotes[0]["id"] == lote["batch_id"] and lotes[0]["live_transactions"] == 2
    linhas = ok(call_tool(mcp_client, c.token, "imports_list", {"batch_id": lote["batch_id"]}))["rows"]
    assert {r["title"] for r in linhas} == {"Uber", "Padaria"}

    previa = ok(call_tool(mcp_client, c.token, "transactions_bulk_preview", {
        "action": "delete", "filters": {"import_batch_id": lote["batch_id"]},
    }))
    assert previa["count"] == 2
    ok(call_tool(mcp_client, c.token, "transactions_bulk_delete", {"confirmation_token": previa["confirmation_token"]}))
    assert ok(call_tool(mcp_client, c.token, "imports_list", {}))["batches"][0]["live_transactions"] == 0
    # Desfeita, as mesmas linhas voltam a entrar (ADR 0036) — como no app.
    de_novo = ok(call_tool(mcp_client, c.token, "imports_commit", {
        "idempotency_key": chave(), "space": "Casa",
        "rows": [{"date": c.hoje.isoformat(), "title": "Uber", "amount": "23.00"},
                 {"date": c.hoje.isoformat(), "title": "Padaria", "amount": "9.50"}],
    }))
    assert (de_novo["imported"], de_novo["duplicate"]) == (2, 0)
    # O lote é de quem importou: nem outro membro do MESMO espaço o vê.
    token_joao = issue_token(db_session, c.joao)
    assert ok(call_tool(mcp_client, token_joao, "imports_list", {}))["batches"] == []
    assert ok(call_tool(mcp_client, c.token_bob, "imports_list", {}))["batches"] == []


# --- alteração em massa --------------------------------------------------------------------------

def test_recategorizar_tag_e_marcar_como_pago_em_massa(mcp_client, db_session, c):
    db_session.add(Tag(workspace_id=c.pessoal.id, name="viagem"))
    db_session.commit()
    a = _cria(mcp_client, c, title="Hotel", amount="300.00", category="Lazer", payment_method="pix",
              settled=False, date=(c.hoje + timedelta(days=3)).isoformat())
    b = _cria(mcp_client, c, title="Passagem", amount="500.00", category="Transporte", payment_method="pix",
              settled=False, date=(c.hoje + timedelta(days=3)).isoformat())
    ids = [a["id"], b["id"]]
    for acao, extra in (("recategorize", {"category": "Outros"}), ("tag", {"tag": "viagem"}), ("settle", {})):
        previa = ok(call_tool(mcp_client, c.token, "transactions_bulk_preview", {"action": acao, "transaction_ids": ids, **extra}))
        assert previa["count"] == 2, (acao, previa)
        feito = ok(call_tool(mcp_client, c.token, "transactions_bulk_update", {"confirmation_token": previa["confirmation_token"]}))
        assert feito["count"] == 2 and feito["action"] == acao
    for i in ids:
        tx = ok(call_tool(mcp_client, c.token, "transactions_get", {"transaction_id": i}))["transaction"]
        assert tx["category"]["name"] == "Outros" and tx["tags"] == ["viagem"] and tx["settled"] is True
    # Já têm a tag: tag de novo não alcança ninguém; untag alcança os dois.
    assert ok(call_tool(mcp_client, c.token, "transactions_bulk_preview", {"action": "tag", "transaction_ids": ids, "tag": "viagem"}))["count"] == 0
    assert ok(call_tool(mcp_client, c.token, "transactions_bulk_preview", {"action": "untag", "transaction_ids": ids, "tag": "viagem"}))["count"] == 2


def test_massa_recusa_se_o_conjunto_mudou(mcp_client, c):
    a = _cria(mcp_client, c, title="Hotel", amount="300.00", category="Lazer")
    previa = ok(call_tool(mcp_client, c.token, "transactions_bulk_preview", {"action": "recategorize", "transaction_ids": [a["id"]], "category": "Outros"}))
    ok(call_tool(mcp_client, c.token, "transactions_update", {"transaction_id": a["id"], "status": "cancelled"}))
    ok(call_tool(mcp_client, c.token, "transactions_delete", {"transaction_id": a["id"]}))
    erro = err(call_tool(mcp_client, c.token, "transactions_bulk_update", {"confirmation_token": previa["confirmation_token"]}))
    assert erro["code"] == "CONFLICT"


# --- histórico -----------------------------------------------------------------------------------

def test_historico_do_lancamento(mcp_client, db_session, c):
    tx = _cria(mcp_client, c, title="Mercado", amount="80.00")
    ok(call_tool(mcp_client, c.token, "transactions_update", {"transaction_id": tx["id"], "amount": "95.00"}))
    ok(call_tool(mcp_client, c.token, "transactions_delete", {"transaction_id": tx["id"]}))
    ok(call_tool(mcp_client, c.token, "transactions_restore", {"transaction_id": tx["id"]}))
    hist = ok(call_tool(mcp_client, c.token, "transactions_history", {"transaction_id": tx["id"]}))["entries"]
    acoes = [e["action"] for e in hist]
    # A edição logo depois de criar (mesmo minuto) é uma entrada própria, não
    # um antes → depois escondido dentro do "Criado".
    assert acoes == ["restored", "deleted", "updated", "created"], acoes
    assert hist[-1]["changes"] == []
    valor = next(e for e in hist if any(ch["field"] == "amount" for ch in e["changes"]))
    mudanca = next(ch for ch in valor["changes"] if ch["field"] == "amount")
    assert (mudanca["before"], mudanca["after"]) == ("80.00", "95.00")
    assert all(e["via_ai"] and e["client"] == "Cliente de teste" and e["by"]["name"] == "Alice Souza" for e in hist)


def test_historico_so_para_quem_ve_o_lancamento(mcp_client, db_session, c):
    pessoal = cria_despesa(mcp_client, c.alice, c.pessoal, title="Presente", amount="200.00", day=c.hoje)
    token_joao = issue_token(db_session, c.joao)
    assert err(call_tool(mcp_client, token_joao, "transactions_history", {"transaction_id": pessoal["id"]}))["code"] == "NOT_FOUND"
    assert err(call_tool(mcp_client, c.token_bob, "transactions_history", {"transaction_id": pessoal["id"]}))["code"] == "NOT_FOUND"


# --- perfil ----------------------------------------------------------------------------------------

def test_perfil_diz_a_versao_e_o_que_o_servidor_sabe(mcp_client, c):
    from app.mcp.version import SERVER_VERSION

    perfil = ok(call_tool(mcp_client, c.token, "profile_get", {}))
    assert perfil["server_version"] == SERVER_VERSION
    assert {"transaction_items", "account_ledger", "history", "attachment_from_chat"} <= set(perfil["capabilities"])
