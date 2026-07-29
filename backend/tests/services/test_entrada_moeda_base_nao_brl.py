"""Entrada de valores num workspace cuja moeda-base NÃO é BRL.

Este arquivo existe porque havia um buraco inteiro de cobertura: toda a suíte de
moeda testava a *migração* da moeda-base (`test_base_currency_conversion.py`) ou
a conversão de estrangeiro num workspace em BRL. Ninguém testava **criar** um
lançamento depois da troca — e era exatamente ali que o app errava:

- `ExchangeRateStore.get_or_fetch` devolve X→**BRL** por contrato, mas os quatro
  caminhos de entrada tratavam esse número como X→**base**. Com base USD, uma
  despesa de EUR 50 virava 315 USD (a taxa EUR→BRL aplicada como se fosse
  EUR→USD).
- Pior e mais comum: os formulários mandam `currency` por default. Com o default
  fixo em "BRL", uma despesa comum num workspace em USD era tratada como
  ESTRANGEIRA e "convertida" com taxa 1,0 — 100 reais viravam 100 dólares.
- E o import/bulk gravava `currency="BRL"` literal, então toda linha importada
  caía fora das agregações (que filtram `currency == base`) e sumia sem aviso.

A âncora dos números: USD→BRL = 5,00 e EUR→BRL = 6,00 na data usada, logo
EUR→USD = 1,20.
"""
from datetime import date, datetime, UTC
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.models.exchange_rate import ExchangeRate
from app.models.income import Income
from app.models.transaction import Transaction
from app.core.jwt import create_access_token
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.services.exchange_rate_store import ExchangeRateStore

OCC = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
USD_BRL = Decimal("5.00")
EUR_BRL = Decimal("6.00")


@pytest.fixture(name="client")
def client_fixture(override_get_session):
    return TestClient(app)


@pytest.fixture(autouse=True)
def sem_rede(monkeypatch):
    """Cotação vem do store: ir à rede num teste esconderia o erro de taxa."""
    from app.services.currency_service import CurrencyService

    def _boom(*args, **kwargs):
        raise AssertionError("entrada de lançamento tentou buscar cotação na rede")

    monkeypatch.setattr(CurrencyService, "get_rate_sync", _boom)


def _seed_rates(db: Session, *days: date) -> None:
    for dia in days:
        for moeda, taxa in (("USD", USD_BRL), ("EUR", EUR_BRL)):
            existe = db.exec(
                select(ExchangeRate).where(
                    ExchangeRate.currency == moeda, ExchangeRate.rate_date == dia
                )
            ).first()
            if not existe:
                db.add(ExchangeRate(
                    currency=moeda, rate_date=dia, rate=taxa, source="ptax"
                ))
    db.flush()


@pytest.fixture(name="ws_usd")
def ws_usd_fixture(db_session: Session):
    """Workspace com moeda-base USD + um membro owner."""
    user = User(name="Dono", email="usd@t.com", password_hash="h")
    db_session.add(user)
    ws = Workspace(name="WS-USD", base_currency="USD")
    db_session.add(ws)
    db_session.flush()
    db_session.add(WorkspaceMembership(
        workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.owner
    ))
    _seed_rates(db_session, OCC.date(), date.today())
    db_session.commit()
    token = create_access_token(data={"sub": str(user.id)})
    return {"ws": ws, "user": user, "headers": {"Cookie": f"access_token={token}"}}


# --- a taxa cruzada ---------------------------------------------------------


def test_rate_between_usa_a_taxa_cruzada(db_session: Session, ws_usd):
    """EUR→USD = (EUR→BRL) / (USD→BRL) = 6 / 5 = 1,20."""
    taxa, fonte = ExchangeRateStore.rate_between(db_session, "EUR", "USD", OCC.date())
    assert taxa == Decimal("6.00") / Decimal("5.00")
    # Taxa cruzada não é PTAX: a PTAX só é oficial CONTRA o real
    assert fonte == "market"

    # E contra BRL continua sendo a taxa direta, com o selo oficial preservado
    taxa_brl, fonte_brl = ExchangeRateStore.rate_between(db_session, "EUR", "BRL", OCC.date())
    assert (taxa_brl, fonte_brl) == (EUR_BRL, "ptax")

    # BRL→USD é o inverso da cotação do dólar (1 / 5)
    taxa_inv, _ = ExchangeRateStore.rate_between(db_session, "BRL", "USD", OCC.date())
    assert taxa_inv == Decimal("1") / USD_BRL


# --- despesa ----------------------------------------------------------------


def _payload(user_id: int, **kw) -> dict:
    corpo = {
        "title": "Compra",
        "total_amount": "50.00",
        "transaction_date": OCC.isoformat(),
        "payers": [{"user_id": user_id, "amount": "50.00"}],
        "splits": [{"user_id": user_id, "split_method": "equal", "input_value": "0"}],
    }
    corpo.update(kw)
    return corpo


def test_despesa_sem_moeda_nasce_na_base_e_nao_e_convertida(client, db_session, ws_usd):
    """Sem `currency` no corpo, a despesa é NATIVA na moeda do workspace.

    Antes o schema trazia "BRL" fixo: o backend via moeda != base, tratava como
    estrangeira e convertia — com taxa BRL→BRL = 1,0, gravando o mesmo número
    como se fossem dólares.
    """
    ws, user = ws_usd["ws"], ws_usd["user"]
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/",
        json=_payload(user.id),
        headers=ws_usd["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["currency"] == "USD"
    assert Decimal(body["total_amount"]) == Decimal("50.00")
    # Nativo: nada de proveniência estrangeira inventada
    assert body["original_currency"] is None
    assert body["exchange_rate"] is None


def test_despesa_estrangeira_converte_pela_taxa_cruzada(client, db_session, ws_usd):
    """EUR 50 num workspace USD = 60 USD (50 × 6/5), não 300 (50 × 6)."""
    ws, user = ws_usd["ws"], ws_usd["user"]
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/",
        json=_payload(user.id, currency="EUR"),
        headers=ws_usd["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["currency"] == "USD"
    assert Decimal(body["total_amount"]) == Decimal("60.00")
    assert body["original_currency"] == "EUR"
    assert Decimal(body["original_amount"]) == Decimal("50.00")
    # A divisão acompanha o total convertido (invariante do ADR 0001)
    assert sum(Decimal(p["amount"]) for p in body["payers"]) == Decimal("60.00")
    assert sum(Decimal(s["computed_amount"]) for s in body["splits"]) == Decimal("60.00")


def test_despesa_em_real_num_workspace_em_dolar(client, db_session, ws_usd):
    """BRL 50 num workspace USD = 10 USD (50 / 5) — o caso que mais dói, porque
    "BRL" é o que o formulário mandava por default."""
    ws, user = ws_usd["ws"], ws_usd["user"]
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/",
        json=_payload(user.id, currency="BRL"),
        headers=ws_usd["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["currency"] == "USD"
    assert Decimal(body["total_amount"]) == Decimal("10.00")
    assert body["original_currency"] == "BRL"


# --- renda ------------------------------------------------------------------


def test_renda_segue_a_mesma_regra(client, db_session, ws_usd):
    ws = ws_usd["ws"]
    headers = ws_usd["headers"]

    nativa = client.post(
        f"/api/v1/workspaces/{ws.id}/income/",
        json={"title": "Salário", "amount": "1000.00", "received_at": OCC.isoformat()},
        headers=headers,
    )
    assert nativa.status_code == 200, nativa.text
    assert nativa.json()["currency"] == "USD"
    assert Decimal(nativa.json()["amount"]) == Decimal("1000.00")

    estrangeira = client.post(
        f"/api/v1/workspaces/{ws.id}/income/",
        json={
            "title": "Freela", "amount": "100.00",
            "currency": "EUR", "received_at": OCC.isoformat(),
        },
        headers=headers,
    )
    assert estrangeira.status_code == 200, estrangeira.text
    corpo = estrangeira.json()
    assert corpo["currency"] == "USD"
    assert Decimal(corpo["amount"]) == Decimal("120.00")  # 100 × 6/5
    assert corpo["original_currency"] == "EUR"


# --- import / bulk ----------------------------------------------------------


def test_import_grava_na_moeda_base_e_entra_nos_totais(client, db_session, ws_usd):
    """Linha importada com `currency="BRL"` fixo ficava fora de TODA agregação."""
    ws = ws_usd["ws"]
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/imports/commit",
        json={
            "filename": "extrato.csv",
            "rows": [{
                "line": 1, "title": "Mercado", "total_amount": "42.00",
                "transaction_date": OCC.isoformat(), "decision": "import",
            }],
        },
        headers=ws_usd["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.json()["imported"] == 1

    tx = db_session.exec(
        select(Transaction).where(Transaction.workspace_id == ws.id)
    ).one()
    assert tx.currency == "USD"

    # E aparece no resumo do mês (a prova de que não caiu fora do filtro)
    resumo = client.get(
        f"/api/v1/workspaces/{ws.id}/analytics/summary?month=2026-07",
        headers=ws_usd["headers"],
    ).json()
    assert resumo["base_currency"] == "USD"
    assert Decimal(str(resumo["total_expenses"])) == Decimal("42.00")
    assert resumo["excluded_foreign_count"] == 0


def test_bulk_grava_na_moeda_base(client, db_session, ws_usd):
    ws = ws_usd["ws"]
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/bulk",
        json=[{"title": "Uber", "total_amount": "15.00", "transaction_date": OCC.isoformat()}],
        headers=ws_usd["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.json()["created"] == 1
    tx = db_session.exec(
        select(Transaction).where(Transaction.workspace_id == ws.id)
    ).one()
    assert tx.currency == "USD"


# --- recorrência ------------------------------------------------------------


def test_recorrente_materializa_na_moeda_base(client, db_session, ws_usd):
    """A instância nasce na base, e a estrangeira usa a taxa cruzada do dia."""
    ws, user = ws_usd["ws"], ws_usd["user"]
    headers = ws_usd["headers"]
    hoje = date.today()

    res = client.post(
        f"/api/v1/workspaces/{ws.id}/recurring",
        json={
            "title": "Assinatura", "base_amount": "10.00", "currency": "EUR",
            "frequency": "monthly", "day_of_month": hoje.day,
            "payer_user_id": user.id,
        },
        headers=headers,
    )
    assert res.status_code == 200, res.text

    instancia = db_session.exec(
        select(Transaction).where(
            Transaction.workspace_id == ws.id,
            Transaction.recurring_expense_id.is_not(None),
        )
    ).first()
    assert instancia is not None, "a recorrência não materializou"
    assert instancia.currency == "USD"
    assert instancia.total_amount == Decimal("12.00")  # 10 × 6/5, sem IOF (sem cartão)
    assert instancia.original_currency == "EUR"


def test_renda_recorrente_materializa_na_moeda_base(client, db_session, ws_usd):
    ws = ws_usd["ws"]
    hoje = date.today()

    res = client.post(
        f"/api/v1/workspaces/{ws.id}/recurring-income",
        json={
            "title": "Salário", "base_amount": "100.00", "currency": "EUR",
            "frequency": "monthly", "day_of_month": hoje.day,
        },
        headers=ws_usd["headers"],
    )
    assert res.status_code == 200, res.text

    entrada = db_session.exec(
        select(Income).where(
            Income.workspace_id == ws.id, Income.recurring_income_id.is_not(None)
        )
    ).first()
    assert entrada is not None, "a renda recorrente não materializou"
    assert entrada.currency == "USD"
    assert entrada.amount == Decimal("120.00")
    assert entrada.original_currency == "EUR"


# --- cartão e conta ---------------------------------------------------------


def test_cartao_e_conta_nascem_na_moeda_base(client, db_session, ws_usd):
    ws = ws_usd["ws"]
    headers = ws_usd["headers"]

    cartao = client.post(
        f"/api/v1/workspaces/{ws.id}/credit-cards/",
        json={"name": "Nubank", "limit": "1000.00", "closing_day": 5, "due_day": 15},
        headers=headers,
    )
    assert cartao.status_code == 200, cartao.text
    assert cartao.json()["currency"] == "USD"

    conta = client.post(
        f"/api/v1/workspaces/{ws.id}/payment-accounts",
        json={"name": "Corrente", "type": "checking"},
        headers=headers,
    )
    assert conta.status_code == 200, conta.text
    assert conta.json()["currency"] == "USD"


# --- onboarding -------------------------------------------------------------


def test_onboarding_nasce_na_moeda_base(client, db_session, ws_usd):
    """O onboarding era o 10º (e último) caminho de entrada fora da regra.

    `POST /auth/onboarding` construía `Income(...)` e `CreditCard(...)` sem passar
    `currency`, então os dois herdavam o default "BRL" do model. Num workspace em
    USD o salário nascia invisível: toda agregação filtra `currency == base`, e o
    formulário ainda exibia o símbolo da moeda-base — a UI prometia US$ e o banco
    gravava BRL.
    """
    ws, user = ws_usd["ws"], ws_usd["user"]
    headers = ws_usd["headers"]

    res = client.post(
        "/api/v1/auth/onboarding",
        json={
            "salary": "4000.00",
            "credit_card_name": "Nubank",
            "credit_card_limit": "2000.00",
            "credit_card_closing_day": 10,
        },
        headers=headers,
    )
    assert res.status_code == 200, res.text

    renda = db_session.exec(select(Income).where(Income.workspace_id == ws.id)).first()
    assert renda is not None
    assert renda.currency == "USD"

    from app.models.credit_card import CreditCard

    cartao = db_session.exec(
        select(CreditCard).where(CreditCard.workspace_id == ws.id)
    ).first()
    assert cartao is not None
    assert cartao.currency == "USD"

    # E a renda aparece de fato nos totais do mês (o filtro de moeda casa)
    mes = renda.received_at.strftime("%Y-%m")
    resumo = client.get(
        f"/api/v1/workspaces/{ws.id}/analytics/summary?month={mes}", headers=headers
    )
    assert resumo.status_code == 200, resumo.text
    assert Decimal(resumo.json()["total_income"]) == Decimal("4000.00")
    assert Decimal(resumo.json()["my_income"]) == Decimal("4000.00")
    assert renda.user_id == user.id


def test_onboarding_recusa_workspace_compartilhado(client, db_session, ws_usd):
    """Onboarding grava a renda DA PESSOA — nunca no workspace de outra família.

    Quem se cadastra por convite nasce com dois workspaces, e o cliente mandava o
    `currentWorkspaceId`, escolhido como `workspaces[0]` de uma listagem que não
    tinha ORDER BY. O salário podia cair no workspace compartilhado.
    """
    convidado = User(name="Convidado", email="convidado@t.com", password_hash="h")
    db_session.add(convidado)
    db_session.flush()
    # Membro (não owner) do workspace de outra pessoa...
    db_session.add(WorkspaceMembership(
        workspace_id=ws_usd["ws"].id, user_id=convidado.id, role=WorkspaceRole.member
    ))
    # ...e owner do próprio
    proprio = Workspace(name="Meu Workspace", base_currency="USD")
    db_session.add(proprio)
    db_session.flush()
    db_session.add(WorkspaceMembership(
        workspace_id=proprio.id, user_id=convidado.id, role=WorkspaceRole.owner
    ))
    db_session.commit()

    token = create_access_token(data={"sub": str(convidado.id)})
    headers = {"Cookie": f"access_token={token}"}

    # Apontar explicitamente para o compartilhado é recusado
    negado = client.post(
        "/api/v1/auth/onboarding",
        json={"workspace_id": ws_usd["ws"].id, "salary": "1000.00"},
        headers=headers,
    )
    assert negado.status_code == 403, negado.text

    # Sem workspace_id, cai no PRÓPRIO
    ok = client.post(
        "/api/v1/auth/onboarding", json={"salary": "1000.00"}, headers=headers
    )
    assert ok.status_code == 200, ok.text
    renda = db_session.exec(
        select(Income).where(Income.user_id == convidado.id)
    ).first()
    assert renda is not None
    assert renda.workspace_id == proprio.id


# --- financiamento ----------------------------------------------------------


def test_financiamento_nasce_na_moeda_base_e_aparece_no_endividamento(
    client, db_session, ws_usd
):
    """O financiamento era o último caminho de entrada com "BRL" fixo.

    Como `FinancingCreate` nem tinha o campo, ele herdava o default do model.
    Num workspace em USD isso o tornava INVISÍVEL: `LiabilityService._financings`
    filtra `Financing.currency == base`, então o painel de Endividamento mostrava
    zero — e pagar a parcela gerava uma despesa em "BRL" que caía fora de
    dívidas, relatórios e previsão. Sem nenhum aviso, nos dois casos.
    """
    ws = ws_usd["ws"]
    headers = ws_usd["headers"]

    res = client.post(
        f"/api/v1/workspaces/{ws.id}/financing",
        json={
            "title": "Carro",
            "total_amount": "12000.00",
            "interest_rate": "0.01",
            "start_date": OCC.date().isoformat(),
            "installments_count": 12,
            "method": "PRICE",
        },
        headers=headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["currency"] == "USD"
    fin_id = res.json()["id"]

    # Visível no panorama de endividamento (o filtro de moeda passa a casar)
    overview = client.get(
        f"/api/v1/workspaces/{ws.id}/liabilities/overview?month={OCC.strftime('%Y-%m')}",
        headers=headers,
    )
    assert overview.status_code == 200, overview.text
    corpo = overview.json()
    assert [f["id"] for f in corpo["financings"]] == [fin_id]
    assert Decimal(corpo["totals"]["financing_outstanding"]) > 0

    # E a despesa gerada ao pagar entra nos totais do mês, em vez de sumir
    pago = client.post(
        f"/api/v1/workspaces/{ws.id}/financing/{fin_id}/installments/1/pay",
        headers=headers,
    )
    assert pago.status_code == 200, pago.text
    despesa = db_session.get(Transaction, pago.json()["transaction_id"])
    assert despesa.currency == "USD"

    mes = despesa.transaction_date.strftime("%Y-%m")
    resumo = client.get(
        f"/api/v1/workspaces/{ws.id}/analytics/summary?month={mes}", headers=headers
    )
    assert resumo.status_code == 200, resumo.text
    assert Decimal(resumo.json()["total_expenses"]) >= despesa.total_amount
    assert resumo.json()["excluded_foreign_count"] == 0


# --- normalização de caixa --------------------------------------------------


def test_moeda_em_caixa_baixa_e_normalizada(client, db_session, ws_usd):
    """`"usd"` tem que virar `"USD"`: a comparação com a base é igualdade de
    string, e a minúscula cairia fora de todos os totais sem nenhum sinal."""
    ws, user = ws_usd["ws"], ws_usd["user"]
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/",
        json=_payload(user.id, currency="usd"),
        headers=ws_usd["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.json()["currency"] == "USD"
    assert Decimal(res.json()["total_amount"]) == Decimal("50.00")
    assert res.json()["original_currency"] is None
