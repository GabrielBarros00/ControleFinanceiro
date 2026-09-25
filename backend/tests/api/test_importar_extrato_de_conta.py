"""Importação de extrato de CONTA (ADR 0037).

Importado como despesa, o salário que caiu virava gasto, a transferência para a
poupança virava gasto e o pagamento da fatura somava de novo as compras do
cartão. Aqui cada linha tem sentido (entrou/saiu) e classificação, e vira o
registro que o app já tem para aquilo — pelo comando da tela.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.jwt import create_access_token
from app.domain.dates import civil_instant, month_key, today_local
from app.main import app
from app.models.account_ledger import AccountTransfer
from app.models.attachment import Attachment
from app.models.credit_card import CardStatement, CreditCard, StatementPayment, StatementStatus
from app.models.income import Income
from app.models.transaction import Transaction
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole

client = TestClient(app)
HOJE = today_local()
API = "/api/v1/me/imports"


@pytest.fixture(name="cena")
def cena_fixture(db_session: Session, override_get_session):
    dona = User(name="Dona", email="extrato@t.com", password_hash="h", report_currency="BRL")
    outra = User(name="Outra", email="extrato-outra@t.com", password_hash="h", report_currency="BRL")
    db_session.add_all([dona, outra])
    casa = Workspace(name="Casa", base_currency="BRL")
    so_leitura = Workspace(name="Só leitura", base_currency="BRL")
    db_session.add_all([casa, so_leitura])
    db_session.flush()
    db_session.add(WorkspaceMembership(workspace_id=casa.id, user_id=dona.id, role=WorkspaceRole.owner))
    db_session.add(WorkspaceMembership(workspace_id=so_leitura.id, user_id=dona.id, role=WorkspaceRole.viewer))
    cartao = CreditCard(name="Nubank Roxinho", limit=Decimal("5000.00"), closing_day=25, due_day=5,
                        currency="BRL", owner_user_id=dona.id)
    db_session.add(cartao)
    db_session.commit()
    h = {"Cookie": f"access_token={create_access_token(data={'sub': str(dona.id)})}"}
    h_outra = {"Cookie": f"access_token={create_access_token(data={'sub': str(outra.id)})}"}
    contas = {}
    for nome in ("Itaú", "Poupança Itaú"):
        r = client.post("/api/v1/me/payment-accounts", json={"name": nome, "type": "checking", "currency": "BRL"}, headers=h)
        assert r.status_code == 200, r.text
        contas[nome] = r.json()["id"]
    for nome, abertura in (("Itaú", "5000.00"), ("Poupança Itaú", "0.00")):
        r = client.put(f"/api/v1/me/payment-accounts/{contas[nome]}/opening-balance",
                       json={"amount": abertura, "as_of": (HOJE - timedelta(days=60)).isoformat()}, headers=h)
        assert r.status_code == 200, r.text
    # Uma compra de 40 dias atrás: a fatura dela já fechou (fecha dia 25) e tem saldo.
    compra = HOJE - timedelta(days=40)
    r = client.post(f"/api/v1/workspaces/{casa.id}/transactions/", json={
        "title": "Tênis", "total_amount": "300.00", "transaction_date": civil_instant(compra).isoformat(),
        "billing_month": month_key(compra), "payment_method": "credit_card", "credit_card_id": cartao.id,
        "payers": [{"user_id": dona.id, "amount": "300.00", "payment_method": "credit_card"}],
        "splits": [{"user_id": dona.id, "split_method": "fixed", "input_value": "300.00"}],
    }, headers=h)
    assert r.status_code == 200, r.text
    return {"db": db_session, "h": h, "h_outra": h_outra, "dona": dona.id, "casa": casa.id,
            "so_leitura": so_leitura.id, "cartao": cartao.id, "itau": contas["Itaú"], "poupanca": contas["Poupança Itaú"]}


def _dia(delta=0):
    return civil_instant(HOJE - timedelta(days=delta)).isoformat()


def _linhas(cena, **extra):
    return [
        {"line": 2, "title": "SALARIO EMPRESA", "total_amount": "5000.00", "transaction_date": _dia(3), "direction": "in",
         "classification": "income", "income_category": "Salário", "external_id": "A1"},
        {"line": 3, "title": "MERCADO EXTRA", "total_amount": "89.90", "transaction_date": _dia(2), "direction": "out",
         "classification": "expense", "space_id": cena["casa"], "external_id": "A2"},
        {"line": 4, "title": "PAGAMENTO FATURA NUBANK", "total_amount": "300.00", "transaction_date": _dia(1),
         "direction": "out", "classification": "statement_payment", "card_id": cena["cartao"], "external_id": "A3"},
        {"line": 5, "title": "TRANSF MESMA TITULARIDADE POUPANCA", "total_amount": "1000.00", "transaction_date": _dia(1),
         "direction": "out", "classification": "transfer", "counterpart_account_id": cena["poupanca"], "external_id": "A4"},
    ]


def _grava(cena, linhas, conta=None, headers=None):
    r = client.post(f"{API}/commit", json={"account_id": conta or cena["itau"], "filename": "itau.csv", "rows": linhas},
                    headers=headers or cena["h"])
    assert r.status_code == 200, r.text
    return r.json()


def _saldo(cena, conta):
    r = client.get("/api/v1/me/balance", headers=cena["h"])
    assert r.status_code == 200, r.text
    return Decimal(next(a["balance"] for a in r.json()["accounts"] if a["account_id"] == conta))


def test_previa_preserva_o_sinal_e_sugere_a_classificacao(cena):
    csv = (
        "Data;Descricao;Valor;Id\n"
        f"{(HOJE - timedelta(days=3)).strftime('%d/%m/%Y')};SALARIO EMPRESA;5.000,00;A1\n"
        f"{(HOJE - timedelta(days=2)).strftime('%d/%m/%Y')};MERCADO EXTRA;-89,90;A2\n"
        f"{(HOJE - timedelta(days=1)).strftime('%d/%m/%Y')};PAGAMENTO FATURA NUBANK;-300,00;A3\n"
        f"{(HOJE - timedelta(days=1)).strftime('%d/%m/%Y')};TRANSF MESMA TITULARIDADE POUPANCA;-1.000,00;A4\n"
    )
    r = client.post(f"{API}/parse", data={
        "account_id": str(cena["itau"]), "date_column": "Data", "description_column": "Descricao",
        "amount_column": "Valor", "date_format": "%d/%m/%Y", "delimiter": ";", "decimal_separator": ",", "id_column": "Id",
    }, files={"file": ("itau.csv", csv.encode(), "text/csv")}, headers=cena["h"])
    assert r.status_code == 200, r.text
    linhas = r.json()["rows"]
    assert [(x["direction"], x["total_amount"], x["external_id"], x["suggested_classification"]) for x in linhas] == [
        ("in", "5000.00", "A1", "income"),
        ("out", "89.90", "A2", "expense"),
        ("out", "300.00", "A3", "statement_payment"),
        ("out", "1000.00", "A4", "transfer"),
    ]
    assert linhas[2]["suggested_card_id"] == cena["cartao"]
    assert linhas[3]["suggested_account_id"] == cena["poupanca"]


def test_cada_linha_vira_o_registro_do_que_ela_e(cena):
    db = cena["db"]
    resultado = _grava(cena, _linhas(cena))
    assert (resultado["imported"], resultado["skipped"]) == (4, 0), resultado
    assert resultado["by_classification"] == {"income": 1, "expense": 1, "statement_payment": 1, "transfer": 1}

    renda = db.exec(select(Income).where(Income.title == "SALARIO EMPRESA")).one()
    assert (renda.account_id, renda.amount, renda.settled_at is not None, renda.category) == (cena["itau"], Decimal("5000.00"), True, "Salário")
    despesa = db.exec(select(Transaction).where(Transaction.title == "MERCADO EXTRA")).one()
    assert (despesa.workspace_id, despesa.total_amount, despesa.settled_at is not None) == (cena["casa"], Decimal("89.90"), True)
    assert despesa.payers[0].account_id == cena["itau"]
    transferencia = db.exec(select(AccountTransfer).where(AccountTransfer.deleted_at.is_(None))).one()
    assert (transferencia.from_account_id, transferencia.to_account_id, transferencia.from_amount) == (cena["itau"], cena["poupanca"], Decimal("1000.00"))
    pagamento = db.exec(select(StatementPayment).where(StatementPayment.deleted_at.is_(None))).one()
    fatura = db.get(CardStatement, pagamento.statement_id)
    assert (pagamento.account_id, pagamento.amount, fatura.status) == (cena["itau"], Decimal("300.00"), StatementStatus.paid)

    # O saldo da conta conta cada movimento UMA vez, com o sinal certo.
    assert _saldo(cena, cena["itau"]) == Decimal("5000.00") + Decimal("5000.00") - Decimal("89.90") - Decimal("300.00") - Decimal("1000.00")
    assert _saldo(cena, cena["poupanca"]) == Decimal("1000.00")


def test_o_mesmo_extrato_de_novo_nao_duplica(cena):
    _grava(cena, _linhas(cena))
    de_novo = _grava(cena, _linhas(cena))
    assert (de_novo["imported"], de_novo["duplicate"]) == (0, 4)
    # Sem id do banco, a impressão digital (dia, sentido, centavos, título) segura.
    sem_id = [{k: v for k, v in linha.items() if k != "external_id"} for linha in _linhas(cena)]
    assert _grava(cena, sem_id)["duplicate"] == 4
    # Com o id do banco, o título reescrito (outro formato de exportação) não engana.
    outro_titulo = [dict(linha, title=linha["title"].title() + " *") for linha in _linhas(cena)]
    assert _grava(cena, outro_titulo)["duplicate"] == 4


def test_linha_que_nao_pode_entrar_vira_problema_com_motivo(cena):
    linhas = [
        {"line": 7, "title": "PADARIA", "total_amount": "12.00", "transaction_date": _dia(1), "direction": "out",
         "classification": "expense"},
        {"line": 8, "title": "TED", "total_amount": "50.00", "transaction_date": _dia(1), "direction": "out",
         "classification": "transfer"},
        {"line": 9, "title": "FEIRA", "total_amount": "30.00", "transaction_date": _dia(1), "direction": "out",
         "classification": "expense", "space_id": cena["so_leitura"]},
        {"line": 10, "title": "RENDA AO CONTRÁRIO", "total_amount": "30.00", "transaction_date": _dia(1),
         "direction": "out", "classification": "income"},
        {"line": 12, "title": "DESPESA QUE ENTROU", "total_amount": "30.00", "transaction_date": _dia(1),
         "direction": "in", "classification": "expense", "space_id": cena["casa"]},
        {"line": 11, "title": "CAFÉ", "total_amount": "8.00", "transaction_date": _dia(1), "direction": "out",
         "classification": "expense", "space_id": cena["casa"]},
    ]
    r = _grava(cena, linhas)
    assert (r["imported"], r["skipped"]) == (1, 5)
    assert {p["line"]: p["reason"] for p in r["problems"]} == {
        12: "despesa é dinheiro que SAIU da conta",
        7: "escolha o espaço da despesa",
        8: "escolha a outra conta (sua) da transferência",
        9: "seu papel no espaço não permite lançar despesa",
        10: "renda é dinheiro que ENTROU na conta",
    }


def test_pagamento_sem_fatura_com_saldo_nao_entra(cena):
    pago = _grava(cena, [_linhas(cena)[2]])
    assert pago["imported"] == 1
    outro = dict(_linhas(cena)[2], title="PAGAMENTO FATURA NUBANK 2", external_id="B9")
    r = _grava(cena, [outro])
    assert r["skipped"] == 1 and "não tem fatura com saldo" in r["problems"][0]["reason"]


def test_desfazer_exclui_e_estorna_o_que_o_extrato_criou(cena):
    db = cena["db"]
    lote = _grava(cena, _linhas(cena))["batch_id"]
    resumo = client.get(API, headers=cena["h"]).json()[0]
    assert (resumo["id"], resumo["account_name"], resumo["live"]) == (lote, "Itaú", 4)

    r = client.post(f"{API}/{lote}/undo", json={}, headers=cena["h"])
    assert r.status_code == 200, r.text
    assert r.json()["undone"] == {"income": 1, "expense": 1, "statement_payment": 1, "transfer": 1}
    db.expire_all()
    assert db.exec(select(Income).where(Income.deleted_at.is_(None))).all() == []
    assert db.exec(select(Transaction).where(Transaction.title == "MERCADO EXTRA", Transaction.deleted_at.is_(None))).all() == []
    assert db.exec(select(AccountTransfer).where(AccountTransfer.deleted_at.is_(None))).all() == []
    assert db.exec(select(StatementPayment).where(StatementPayment.deleted_at.is_(None))).all() == []
    # O estorno devolve a fatura a "fechada": o saldo voltou a existir.
    fatura = db.exec(select(CardStatement).where(CardStatement.card_id == cena["cartao"], CardStatement.status != StatementStatus.open)).one()
    assert fatura.status == StatementStatus.closed
    assert _saldo(cena, cena["itau"]) == Decimal("5000.00")
    assert client.get(API, headers=cena["h"]).json()[0]["live"] == 0

    # Idempotente, e o extrato volta a entrar.
    assert client.post(f"{API}/{lote}/undo", json={}, headers=cena["h"]).json()["undone"] == {}
    assert _grava(cena, _linhas(cena))["imported"] == 4


def test_a_importacao_de_outra_pessoa_nao_aparece(cena):
    lote = _grava(cena, _linhas(cena))["batch_id"]
    assert client.get(API, headers=cena["h_outra"]).json() == []
    assert client.get(f"{API}/{lote}", headers=cena["h_outra"]).status_code == 404
    assert client.post(f"{API}/{lote}/undo", json={}, headers=cena["h_outra"]).status_code == 404
    # A conta de outra pessoa também não serve de origem.
    r = client.post(f"{API}/commit", json={"account_id": cena["itau"], "rows": []}, headers=cena["h_outra"])
    assert r.status_code == 404


def test_detalhe_mostra_cada_linha_com_o_que_ela_virou(cena):
    lote = _grava(cena, _linhas(cena) + [{"line": 6, "title": "IGNORAR", "total_amount": "1.00",
                                         "transaction_date": _dia(1), "direction": "out", "decision": "ignore"}])["batch_id"]
    detalhe = client.get(f"{API}/{lote}", headers=cena["h"]).json()
    assert [(r["line"], r["classification"], r["status"], r["alive"]) for r in detalhe["rows"]] == [
        (2, "income", "imported", True), (3, "expense", "imported", True), (4, "statement_payment", "imported", True),
        (5, "transfer", "imported", True), (6, "expense", "ignored", False),
    ]


def test_desfazer_com_recibo_so_com_confirmacao(cena):
    db = cena["db"]
    lote = _grava(cena, _linhas(cena))["batch_id"]
    despesa = db.exec(select(Transaction).where(Transaction.title == "MERCADO EXTRA")).one()
    db.add(Attachment(workspace_id=cena["casa"], transaction_id=despesa.id, filename="nota.pdf",
                      content_type="application/pdf", size_bytes=10, storage_key="k/n.pdf", uploaded_by_user_id=cena["dona"]))
    db.commit()
    assert client.get(API, headers=cena["h"]).json()[0]["attachments"] == 1
    recusa = client.post(f"{API}/{lote}/undo", json={}, headers=cena["h"])
    assert recusa.status_code == 409 and "1 recibo" in recusa.json()["error"]["message"]
    db.rollback()  # o fim da requisição sem commit (a suíte divide a sessão com a rota)
    ok = client.post(f"{API}/{lote}/undo", json={"confirm_attachments": True}, headers=cena["h"])
    assert ok.status_code == 200 and ok.json()["attachments_removed"] == 1


def test_a_transferencia_vista_pelo_extrato_da_outra_conta_nao_duplica(cena):
    _grava(cena, [_linhas(cena)[3]])  # saiu do Itaú para a Poupança
    espelho = dict(_linhas(cena)[3], title="TRANSF RECEBIDA ITAU", direction="in",
                   counterpart_account_id=cena["itau"], external_id="P1")
    r = _grava(cena, [espelho], conta=cena["poupanca"])
    assert (r["imported"], r["duplicate"]) == (0, 1)
    assert len(cena["db"].exec(select(AccountTransfer).where(AccountTransfer.deleted_at.is_(None))).all()) == 1

