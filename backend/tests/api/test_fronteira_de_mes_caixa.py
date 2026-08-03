"""A virada do mês no CAIXA: fatura, acerto, renda e parcela de financiamento.

`test_fronteira_de_mes.py` cobre a despesa, que é protegida por `billing_month` —
um listener de mapper carimba o mês LOCAL que o cliente manda
(`models/transaction.py`). As quatro fontes de caixa deste arquivo não têm essa
proteção: `StatementPayment.paid_at`, `Settlement.settled_at`, `Income.received_at`
e `AmortizationInstallment.paid_at` são instantes UTC crus, e o ADR 0022 manda o
caixa recortar por eles — não por `billing_month`.

A janela do mês era montada com `datetime.combine` ingênuo sobre o mês de
calendário, ou seja, comparava um mês LOCAL contra colunas em UTC. Uma renda
recebida às 22h de 31 de julho em São Paulo está gravada como
`2026-08-01T01:00Z` e caía no caixa de AGOSTO — um mês em que o dinheiro não se
moveu.

Cada teste fixa esse mesmo instante e exige que o movimento apareça em julho.
"""
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.jwt import create_access_token
from app.main import app
from app.models.credit_card import CardStatement, CreditCard, StatementPayment, StatementStatus
from app.models.financing import (
    AmortizationInstallment,
    AmortizationMethod,
    Financing,
    FinancingStatus,
)
from app.models.income import Income
from app.models.settlement import Settlement
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.services.overview_service import OverviewService

# 31/07/2026 22:00 em Brasília == 01/08/2026 01:00 UTC.
INSTANTE_UTC = datetime(2026, 8, 1, 1, 0, tzinfo=UTC)
JULHO = date(2026, 7, 1)
AGOSTO = date(2026, 8, 1)


@pytest.fixture(name="client")
def client_fixture(override_get_session):
    return TestClient(app)


@pytest.fixture(name="cena")
def cena_fixture(db_session: Session):
    user = User(name="Dona", email="fronteira-caixa@t.com", password_hash="h")
    outro = User(name="Outro", email="fronteira-outro@t.com", password_hash="h")
    db_session.add_all([user, outro])
    workspace = Workspace(name="WS-caixa", base_currency="BRL")
    db_session.add(workspace)
    db_session.flush()
    db_session.add_all([
        WorkspaceMembership(
            workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.owner
        ),
        WorkspaceMembership(
            workspace_id=workspace.id, user_id=outro.id, role=WorkspaceRole.member
        ),
    ])
    db_session.commit()
    token = create_access_token(data={"sub": str(user.id)})
    return {
        "ws_id": workspace.id,
        "user_id": user.id,
        "outro_id": outro.id,
        "headers": {"Cookie": f"access_token={token}"},
    }


def _caixa(db_session, cena, mes: date) -> dict:
    return OverviewService.get_overview(db_session, cena["user_id"], mes, com_acertos=False)


def test_renda_recebida_na_virada_conta_no_mes_local(db_session, cena):
    db_session.add(Income(
        title="Salário", amount=Decimal("5000.00"), currency="BRL",
        received_at=INSTANTE_UTC.replace(tzinfo=None), user_id=cena["user_id"],
    ))
    db_session.commit()

    assert _caixa(db_session, cena, JULHO)["income"] == Decimal("5000.00")
    assert _caixa(db_session, cena, AGOSTO)["income"] == Decimal("0.00")


def test_pagamento_de_fatura_na_virada_conta_no_mes_local(db_session, cena):
    card = CreditCard(
        name="Nubank", limit=Decimal("5000.00"), closing_day=25, due_day=5,
        currency="BRL", owner_user_id=cena["user_id"],
    )
    db_session.add(card)
    db_session.flush()
    statement = CardStatement(
        card_id=card.id, month="2026-07", status=StatementStatus.paid,
        closing_date=datetime(2026, 7, 25), due_date=datetime(2026, 8, 5),
        total_amount=Decimal("300.00"),
    )
    db_session.add(statement)
    db_session.flush()
    db_session.add(StatementPayment(
        statement_id=statement.id, amount=Decimal("300.00"),
        paid_at=INSTANTE_UTC.replace(tzinfo=None),
    ))
    db_session.commit()

    julho = _caixa(db_session, cena, JULHO)
    assert julho["cash_out_breakdown"]["statement_payments"] == Decimal("300.00")
    agosto = _caixa(db_session, cena, AGOSTO)
    assert agosto["cash_out_breakdown"]["statement_payments"] == Decimal("0.00")


def test_acerto_enviado_na_virada_conta_no_mes_local(db_session, cena):
    db_session.add(Settlement(
        workspace_id=cena["ws_id"], from_user_id=cena["user_id"],
        to_user_id=cena["outro_id"], amount=Decimal("120.00"),
        settled_at=INSTANTE_UTC.replace(tzinfo=None),
    ))
    db_session.commit()

    julho = _caixa(db_session, cena, JULHO)
    assert julho["cash_out_breakdown"]["settlements_sent"] == Decimal("120.00")
    agosto = _caixa(db_session, cena, AGOSTO)
    assert agosto["cash_out_breakdown"]["settlements_sent"] == Decimal("0.00")


def test_parcela_de_financiamento_na_virada_conta_no_mes_local(db_session, cena):
    financing = Financing(
        title="Imóvel", total_amount=Decimal("1000.00"), interest_rate=Decimal("0.01"),
        start_date=date(2026, 1, 1), installments_count=10,
        method=AmortizationMethod.SAC, status=FinancingStatus.active,
        currency="BRL", owner_user_id=cena["user_id"],
    )
    db_session.add(financing)
    db_session.flush()
    db_session.add(AmortizationInstallment(
        financing_id=financing.id, installment_number=1,
        due_date=date(2026, 8, 10),
        principal_amount=Decimal("100.00"), interest_amount=Decimal("10.00"),
        total_amount=Decimal("110.00"), remaining_balance=Decimal("900.00"),
        is_paid=True, paid_at=INSTANTE_UTC.replace(tzinfo=None),
    ))
    db_session.commit()

    julho = _caixa(db_session, cena, JULHO)
    assert julho["cash_out_breakdown"]["financing_installments"] == Decimal("110.00")
    agosto = _caixa(db_session, cena, AGOSTO)
    assert agosto["cash_out_breakdown"]["financing_installments"] == Decimal("0.00")
