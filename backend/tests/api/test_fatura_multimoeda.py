"""Cartão numa moeda, workspace em outra: a fatura tem de fechar mesmo assim.

O cenário exato que uma auditoria reproduziu no navegador — moeda de relatório
USD, workspace em BRL, cartão em USD, despesa de R$ 100 no cartão — e o resultado
que ela viu: a compra listada como `−US$ 100,00`, o total da fatura em `US$ 0,00`
e o limite disponível intacto em `US$ 1.000,00`.

A causa era estrutural, não um filtro errado. O ADR 0021 tornou o cartão pessoal
(moeda = a de relatório do dono) e o ADR 0015 grava todo lançamento na moeda-base
do WORKSPACE. As duas nunca conversaram: `compute_statement_total` somava
`total_amount` exigindo `currency == card.currency`, e num cartão USD dentro de
um workspace BRL isso não casava com linha nenhuma. Some sem erro:

- o total da fatura era 0,00 com N compras dentro;
- `available_limit` devolvia o limite inteiro, para sempre;
- fechar a fatura CONGELAVA o zero, e aí o erro virava histórico;
- a listagem exibia as compras (não filtrava moeda) formatadas na moeda do
  cartão, então R$ 100 apareciam como US$ 100 — três populações diferentes na
  mesma tela.

O ADR 0024 separou as duas pernas do lançamento. Estes testes fixam que elas
coexistem sem se contaminar.
"""
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.jwt import create_access_token
from app.domain.dates import civil_instant
from app.main import app
from app.models.credit_card import CreditCard
from app.models.exchange_rate import ExchangeRate
from app.models.transaction import Transaction, TransactionStatus
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.services.credit_card_service import CreditCardService

client = TestClient(app)

DIA = date(2026, 8, 10)
QUANDO = civil_instant(DIA)
# USD→BRL a 5,00: R$ 100 são US$ 20 antes do IOF.
TAXA_USD = Decimal("5.000000")


@pytest.fixture(name="cena")
def cena_fixture(db_session: Session, override_get_session):
    """Workspace em BRL, cartão do dono em USD — as duas moedas em desacordo."""
    user = User(
        name="Dona", email="onda9-fx@t.com", password_hash="h", report_currency="USD"
    )
    db_session.add(user)
    ws = Workspace(name="Casa", base_currency="BRL")
    db_session.add(ws)
    db_session.flush()
    db_session.add(
        WorkspaceMembership(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.owner)
    )
    card = CreditCard(
        name="Cartão gringo", limit=Decimal("1000.00"), closing_day=20, due_day=28,
        currency="USD", owner_user_id=user.id,
    )
    db_session.add(card)
    # A cotação tem de existir na data da compra: sem ela a entrada devolve 422,
    # que é o comportamento certo — melhor recusar do que gravar valor inventado.
    db_session.add_all([
        ExchangeRate(currency="USD", rate_date=DIA, rate=TAXA_USD, source="ptax"),
        ExchangeRate(currency="BRL", rate_date=DIA, rate=Decimal("1.000000"), source="base"),
    ])
    db_session.commit()
    token = create_access_token(data={"sub": str(user.id)})
    return {
        "ws_id": ws.id, "user_id": user.id, "card": card, "card_id": card.id,
        "headers": {"Cookie": f"access_token={token}"},
    }


def _lancar(cena, valor="100.00"):
    return client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/",
        headers=cena["headers"],
        json={
            "title": "Mercado", "total_amount": valor, "currency": "BRL",
            "transaction_date": QUANDO.isoformat(), "payment_method": "credit_card",
            "credit_card_id": cena["card_id"],
            "payers": [{"user_id": cena["user_id"], "amount": valor}],
            "splits": [{"user_id": cena["user_id"], "split_method": "equal",
                        "input_value": "100"}],
        },
    )


def test_as_duas_pernas_coexistem_no_lancamento(db_session, cena):
    """Contábil em BRL (o orçamento da casa), fatura em USD (o que o banco cobra)."""
    resp = _lancar(cena)
    assert resp.status_code == 200, resp.text

    tx = db_session.exec(
        select(Transaction).where(Transaction.workspace_id == cena["ws_id"])
    ).one()
    assert tx.currency == "BRL"
    assert tx.total_amount == Decimal("100.00")
    assert tx.statement_currency == "USD"
    # R$ 100 ÷ 5,00 = US$ 20, mais 3,5% de IOF (compra internacional PARA o
    # cartão, que é quem faz a conversão) = US$ 20,70.
    assert tx.statement_amount == Decimal("20.70")


def test_a_compra_entra_no_total_da_fatura(db_session, cena):
    """O achado: o total era 0,00 com a compra listada logo acima dele."""
    assert _lancar(cena).status_code == 200
    tx = db_session.exec(select(Transaction)).one()

    total = CreditCardService.compute_statement_total(db_session, tx.statement_id)
    assert total == Decimal("20.70"), "a fatura tem de somar a compra, não zero"


def test_a_compra_consome_limite(db_session, cena):
    """`available_limit` devolvia o limite inteiro — o cartão nunca enchia."""
    assert _lancar(cena).status_code == 200

    resp = client.get("/api/v1/me/credit-cards", headers=cena["headers"])
    assert resp.status_code == 200
    cartao = resp.json()[0]
    # `str()` antes do Decimal: esta rota não declara `response_model`, então os
    # valores saem como número JSON e `Decimal(float)` traria a imprecisão do
    # binário junto. Não é o assunto deste teste — só não pode contaminá-lo.
    assert Decimal(str(cartao["committed_amount"])) == Decimal("20.70")
    assert Decimal(str(cartao["available_limit"])) == Decimal("979.30")


def test_listagem_e_total_veem_o_mesmo_conjunto(db_session, cena):
    """As duas populações divergiam em moeda E status; agora são a mesma."""
    assert _lancar(cena).status_code == 200
    tx = db_session.exec(select(Transaction)).one()

    resp = client.get(
        f"/api/v1/me/credit-cards/{cena['card_id']}/statements/{tx.statement_id}",
        headers=cena["headers"],
    )
    assert resp.status_code == 200
    dados = resp.json()
    linhas = dados["transactions"]
    assert len(linhas) == 1
    # A linha carrega o valor DE FATURA, que é o que a tela desenha — antes ela
    # recebia `total_amount` (R$ 100) e o rotulava com a moeda do cartão (US$ 100).
    assert Decimal(linhas[0]["statement_amount"]) == Decimal("20.70")
    assert linhas[0]["statement_currency"] == "USD"
    # E a soma das linhas é o total exibido: nenhum item fora da conta.
    soma = sum(Decimal(t["statement_amount"]) for t in linhas)
    assert soma == Decimal(dados["computed_total"])
    assert dados["excluded_from_total_count"] == 0


def test_cancelada_sai_da_listagem_e_do_total_juntas(db_session, cena):
    """A listagem não filtrava status: a cancelada aparecia e não somava."""
    assert _lancar(cena).status_code == 200
    tx = db_session.exec(select(Transaction)).one()
    statement_id = tx.statement_id
    tx.status = TransactionStatus.cancelled
    db_session.add(tx)
    db_session.commit()

    resp = client.get(
        f"/api/v1/me/credit-cards/{cena['card_id']}/statements/{statement_id}",
        headers=cena["headers"],
    )
    dados = resp.json()
    assert dados["transactions"] == []
    assert Decimal(dados["computed_total"]) == Decimal("0.00")


def test_fechar_congela_o_valor_certo(db_session, cena):
    """Fechar congelava 0,00 e o erro virava histórico imutável."""
    assert _lancar(cena).status_code == 200
    tx = db_session.exec(select(Transaction)).one()

    resp = client.post(
        f"/api/v1/me/credit-cards/{cena['card_id']}/statements/{tx.statement_id}/close",
        headers=cena["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert Decimal(resp.json()["total_amount"]) == Decimal("20.70")
    assert Decimal(resp.json()["computed_total"]) == Decimal("20.70")


def test_compra_na_moeda_do_cartao_nao_leva_iof(db_session, cena):
    """US$ no cartão US$ é compra doméstica PARA o cartão — sem IOF, sem câmbio.

    A perna contábil converte para BRL (a base do workspace) e continua cobrando
    o IOF pelo critério dela; a de fatura não, porque o banco não converte nada.
    A divergência é conhecida e está registrada no ADR 0024.
    """
    resp = client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/",
        headers=cena["headers"],
        json={
            "title": "Assinatura", "total_amount": "20.00", "currency": "USD",
            "transaction_date": QUANDO.isoformat(), "payment_method": "credit_card",
            "credit_card_id": cena["card_id"],
            "payers": [{"user_id": cena["user_id"], "amount": "20.00"}],
            "splits": [{"user_id": cena["user_id"], "split_method": "equal",
                        "input_value": "100"}],
        },
    )
    assert resp.status_code == 200, resp.text

    tx = db_session.exec(select(Transaction)).one()
    assert tx.statement_currency == "USD"
    assert tx.statement_amount == Decimal("20.00"), "sem conversão, sem IOF"
    assert tx.statement_exchange_rate == Decimal("1")
    # A perna contábil: US$ 20 × 5,00 × 1,035 (IOF) = R$ 103,50
    assert tx.currency == "BRL"
    assert tx.total_amount == Decimal("103.50")


def test_editar_o_valor_reancora_a_fatura(db_session, cena):
    """A perna de fatura tem de acompanhar a edição, senão o total fica para trás."""
    assert _lancar(cena).status_code == 200
    tx = db_session.exec(select(Transaction)).one()

    resp = client.put(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/{tx.id}",
        headers=cena["headers"],
        json={"total_amount": "200.00"},
    )
    assert resp.status_code == 200, resp.text

    db_session.refresh(tx)
    assert tx.total_amount == Decimal("200.00")
    assert tx.statement_amount == Decimal("41.40"), "R$ 200 ÷ 5 × 1,035"
    assert CreditCardService.compute_statement_total(db_session, tx.statement_id) == Decimal("41.40")


def test_tirar_o_cartao_tira_a_perna_de_fatura(db_session, cena):
    """Desvincular o cartão tem de esvaziar a fatura junto."""
    assert _lancar(cena).status_code == 200
    tx = db_session.exec(select(Transaction)).one()
    statement_id = tx.statement_id

    resp = client.put(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/{tx.id}",
        headers=cena["headers"],
        json={"credit_card_id": None, "payment_method": "pix"},
    )
    assert resp.status_code == 200, resp.text

    db_session.refresh(tx)
    assert tx.statement_id is None
    assert tx.statement_amount is None
    assert tx.statement_currency is None
    assert CreditCardService.compute_statement_total(db_session, statement_id) == Decimal("0.00")


def test_parcelamento_soma_exatamente_a_compra(db_session, cena):
    """As N parcelas somam a compra na fatura, sem centavo perdido no rateio."""
    resp = client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/",
        headers=cena["headers"],
        json={
            "title": "Notebook", "total_amount": "100.00", "currency": "BRL",
            "transaction_date": QUANDO.isoformat(), "payment_method": "credit_card",
            "credit_card_id": cena["card_id"], "installments_count": 3,
            "payers": [{"user_id": cena["user_id"], "amount": "100.00"}],
            "splits": [{"user_id": cena["user_id"], "split_method": "equal",
                        "input_value": "100"}],
        },
    )
    assert resp.status_code == 200, resp.text

    parcelas = db_session.exec(
        select(Transaction).where(Transaction.installment_group_id.is_not(None))
    ).all()
    assert len(parcelas) == 3
    assert all(p.statement_currency == "USD" for p in parcelas)
    # A soma bate com a compra inteira: 20,70 fatiado em 3 (6,90 cada).
    assert sum((p.statement_amount for p in parcelas), Decimal("0")) == Decimal("20.70")


# ---------------------------------------------------------------------------
# Recorrência: editar o template tem de mover a fatura junto
#
# O caminho de CRIAÇÃO da ocorrência sempre chamou `apply_statement_leg`; o de
# SINCRONIZAÇÃO (`sync_unpaid_instances`, o que roda quando se edita o template)
# atualizava valor, moeda, cartão e `statement_id` e parava aí. Uma assinatura
# mensal é justamente o lançamento que ninguém relança à mão, então a fatura
# ficava presa ao valor da criação para sempre.

def _criar_recorrencia(cena, valor="100.00", card_id=None):
    return client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/recurring",
        headers=cena["headers"],
        json={
            "title": "Assinatura", "base_amount": valor, "currency": "BRL",
            "frequency": "monthly", "day_of_month": DIA.day,
            "start_date": DIA.isoformat(),
            "payment_method": "credit_card",
            "credit_card_id": cena["card_id"] if card_id is None else card_id,
            "payer_user_id": cena["user_id"],
            "split_snapshot": [{"user_id": cena["user_id"], "split_method": "equal",
                                "input_value": "100"}],
        },
    )


def _materializar(cena, recurring_id):
    resp = client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/recurring/generate",
        headers=cena["headers"],
        params={"year": DIA.year, "month": DIA.month},
    )
    assert resp.status_code == 200, resp.text
    return recurring_id


def test_editar_recorrencia_move_a_fatura_junto(db_session, cena):
    """O achado: lançamento virava R$ 200 e a fatura seguia cobrando US$ 20,70."""
    criada = _criar_recorrencia(cena)
    assert criada.status_code == 200, criada.text
    rec_id = criada.json()["id"]
    _materializar(cena, rec_id)

    tx = db_session.exec(select(Transaction)).one()
    assert tx.statement_amount == Decimal("20.70"), "a criação já nascia certa"
    statement_id = tx.statement_id

    resp = client.put(
        f"/api/v1/workspaces/{cena['ws_id']}/recurring/{rec_id}",
        headers=cena["headers"],
        params={"scope": "all"},
        json={"base_amount": "200.00"},
    )
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    tx = db_session.exec(select(Transaction)).one()
    assert tx.total_amount == Decimal("200.00")
    assert tx.statement_amount == Decimal("41.40"), "R$ 200 ÷ 5 × 1,035"
    assert tx.statement_currency == "USD"
    assert CreditCardService.compute_statement_total(db_session, statement_id) == Decimal("41.40")


def test_trocar_o_cartao_da_recorrencia_leva_a_perna_monetaria(db_session, cena):
    """Migrar de fatura carregando a perna do cartão ANTIGO deixava a instância
    fora do total da fatura nova — invisível, contada só em
    `excluded_from_total_count`."""
    outro = CreditCard(
        name="Cartão nacional", limit=Decimal("5000.00"), closing_day=20, due_day=28,
        currency="BRL", owner_user_id=cena["user_id"],
    )
    db_session.add(outro)
    db_session.commit()
    db_session.refresh(outro)

    criada = _criar_recorrencia(cena)
    rec_id = criada.json()["id"]
    _materializar(cena, rec_id)

    resp = client.put(
        f"/api/v1/workspaces/{cena['ws_id']}/recurring/{rec_id}",
        headers=cena["headers"],
        params={"scope": "all"},
        json={"credit_card_id": outro.id},
    )
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    tx = db_session.exec(select(Transaction)).one()
    assert tx.credit_card_id == outro.id
    # Cartão em BRL, lançamento em BRL: sem conversão e sem IOF.
    assert tx.statement_currency == "BRL"
    assert tx.statement_amount == Decimal("100.00")
    assert CreditCardService.compute_statement_total(
        db_session, tx.statement_id
    ) == Decimal("100.00"), "a instância tem de entrar no total da fatura NOVA"
    assert CreditCardService.excluded_from_total_count(
        db_session, tx.statement_id, outro
    ) == 0


def test_tirar_o_cartao_da_recorrencia_esvazia_a_perna(db_session, cena):
    """Simétrico do lançamento avulso: sem cartão, sem perna de fatura."""
    criada = _criar_recorrencia(cena)
    rec_id = criada.json()["id"]
    _materializar(cena, rec_id)
    statement_id = db_session.exec(select(Transaction)).one().statement_id

    resp = client.put(
        f"/api/v1/workspaces/{cena['ws_id']}/recurring/{rec_id}",
        headers=cena["headers"],
        params={"scope": "all"},
        json={"credit_card_id": None, "payment_method": "pix"},
    )
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    tx = db_session.exec(select(Transaction)).one()
    assert tx.statement_id is None
    assert tx.statement_amount is None
    assert tx.statement_currency is None
    assert tx.statement_exchange_rate is None
    assert CreditCardService.compute_statement_total(db_session, statement_id) == Decimal("0.00")


def test_linha_legada_sem_perna_de_fatura_e_contada(db_session, cena):
    """O que a migração não converte tem de aparecer, não sumir calado.

    O backfill é identidade de propósito (não inventa câmbio retroativo), então
    uma compra antiga num cartão de moeda diferente continua fora do total. O que
    não pode é ficar invisível — era assim que a fatura parecia certa estando
    errada.
    """
    db_session.add(Transaction(
        title="Compra antiga", total_amount=Decimal("100.00"), currency="BRL",
        transaction_date=QUANDO, billing_month="2026-08",
        workspace_id=cena["ws_id"], created_by_user_id=cena["user_id"],
        status=TransactionStatus.confirmed,
        credit_card_id=cena["card_id"],
        statement_id=CreditCardService.get_or_create_statement(
            db_session, cena["card"], QUANDO
        ).id,
    ))
    db_session.commit()

    tx = db_session.exec(select(Transaction)).one()
    # O listener carimba a identidade: BRL num cartão USD → fora do total.
    assert tx.statement_currency == "BRL"

    resp = client.get(
        f"/api/v1/me/credit-cards/{cena['card_id']}/statements/{tx.statement_id}",
        headers=cena["headers"],
    )
    dados = resp.json()
    assert Decimal(dados["computed_total"]) == Decimal("0.00")
    assert dados["excluded_from_total_count"] == 1, "a linha fora do total tem de ser anunciada"
