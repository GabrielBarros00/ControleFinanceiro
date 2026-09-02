"""Recorrência em moeda estrangeira: cada materialização converte na data da
ocorrência (re-converte todo mês). Taxa mockada (sem rede)."""
from datetime import date
from decimal import Decimal

import pytest
from sqlmodel import select

from app.models.recurring import RecurringExpense, RecurringIncome, RecurrenceFrequency
from app.models.transaction import PaymentMethod
from app.models.income import Income
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.services import currency_service as cs
from app.services.recurring_service import RecurringService, RecurringIncomeService


@pytest.fixture(autouse=True)
def _mock_rate(monkeypatch):
    monkeypatch.setattr(cs.CurrencyService, "get_rate_sync", lambda *a, **k: (Decimal("5.00"), "ptax"))


def test_recorrencia_despesa_estrangeira_converte_com_iof(db_session, seed_ws):
    user, ws = seed_ws["user"], seed_ws["ws"]
    db_session.add(WorkspaceMembership(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.owner))
    db_session.commit()
    tmpl = RecurringExpense(
        title="Netflix US", base_amount=Decimal("10.00"), currency="USD",
        frequency=RecurrenceFrequency.monthly, interval=1, day_of_month=10,
        workspace_id=ws.id, created_by_user_id=user.id, payer_user_id=user.id,
        payment_method=PaymentMethod.credit_card, is_active=True,
    )
    db_session.add(tmpl)
    db_session.commit()
    db_session.refresh(tmpl)

    tx = RecurringService._create_instance(db_session, tmpl, date(2026, 3, 10), "2026-03")
    db_session.commit()
    assert tx is not None
    # 10 USD × 5,00 × 1,035 (IOF no cartão) = 51,75
    assert tx.total_amount == Decimal("51.75")
    assert tx.currency == "BRL"
    assert tx.original_currency == "USD"
    assert tx.original_amount == Decimal("10.00")
    assert tx.exchange_rate == Decimal("5.00")
    assert tx.rate_source == "ptax"


def test_recorrencia_renda_estrangeira_converte_sem_iof(db_session, seed_ws):
    user, _ws = seed_ws["user"], seed_ws["ws"]
    tmpl = RecurringIncome(
        title="Freela USD", base_amount=Decimal("100.00"), currency="USD",
        frequency=RecurrenceFrequency.monthly, interval=1, day_of_month=5,
        user_id=user.id, is_active=True,
    )
    db_session.add(tmpl)
    db_session.commit()
    db_session.refresh(tmpl)

    created = RecurringIncomeService.generate_due_income(db_session, user.id, date(2026, 3, 10), horizonte_meses=0)
    db_session.commit()
    assert created == 1
    inc = db_session.exec(select(Income).where(Income.recurring_income_id == tmpl.id)).first()
    assert inc.amount == Decimal("500.00")  # 100 × 5,00, sem IOF (renda)
    assert inc.currency == "BRL"
    assert inc.original_currency == "USD"
    assert inc.original_amount == Decimal("100.00")
    assert inc.exchange_rate == Decimal("5.00")
