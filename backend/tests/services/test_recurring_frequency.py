"""Recorrência semanal/mensal/anual: ocorrências e materialização de instâncias."""
from datetime import date, datetime, UTC
from decimal import Decimal

from sqlmodel import select

from app.models.recurring import RecurringExpense, RecurrenceFrequency
from app.models.transaction import Transaction
from app.services.recurring_service import RecurringService


def _template(ws_id, **overrides):
    data = dict(
        title="Assinatura",
        base_amount=Decimal("30.00"),
        frequency=RecurrenceFrequency.monthly,
        day_of_month=10,
        workspace_id=ws_id,
    )
    data.update(overrides)
    return RecurringExpense(**data)


def test_monthly_occurrence_clamps_to_month_end(seed_ws):
    t = _template(seed_ws["ws"].id, day_of_month=31)
    assert RecurringService.occurrences_in_month(t, 2026, 2) == [date(2026, 2, 28)]
    assert RecurringService.occurrences_in_month(t, 2026, 1) == [date(2026, 1, 31)]


def test_weekly_occurrences(seed_ws):
    # Julho/2026: segundas-feiras (weekday 0) caem em 6, 13, 20, 27
    t = _template(seed_ws["ws"].id, frequency=RecurrenceFrequency.weekly, day_of_week=0)
    occs = RecurringService.occurrences_in_month(t, 2026, 7)
    assert occs == [date(2026, 7, 6), date(2026, 7, 13), date(2026, 7, 20), date(2026, 7, 27)]


def test_yearly_only_in_target_month(seed_ws):
    t = _template(seed_ws["ws"].id, frequency=RecurrenceFrequency.yearly, month_of_year=12, day_of_month=25)
    assert RecurringService.occurrences_in_month(t, 2026, 12) == [date(2026, 12, 25)]
    assert RecurringService.occurrences_in_month(t, 2026, 7) == []


def test_generate_creates_due_and_is_idempotent(db_session, seed_ws):
    ws = seed_ws["ws"]
    today = date(2026, 7, 18)  # sábado

    # Mensal dia 10 (vencida), semanal às segundas (6, 13 vencidas), anual em dez (nada)
    monthly = _template(ws.id, title="Aluguel", day_of_month=10)
    weekly = _template(
        ws.id, title="Feira", frequency=RecurrenceFrequency.weekly, day_of_week=0,
        base_amount=Decimal("50.00"),
    )
    yearly = _template(
        ws.id, title="IPVA", frequency=RecurrenceFrequency.yearly, month_of_year=12,
    )
    db_session.add_all([monthly, weekly, yearly])
    db_session.commit()

    created = RecurringService.generate_due_instances(db_session, ws.id, today)
    db_session.commit()
    assert created == 3  # aluguel dia 10 + feira 06/07 e 13/07

    txs = db_session.exec(
        select(Transaction).where(Transaction.workspace_id == ws.id)
    ).all()
    assert len(txs) == 3
    titles = sorted(tx.title for tx in txs)
    assert titles == ["Aluguel", "Feira", "Feira"]

    # Idempotente
    created = RecurringService.generate_due_instances(db_session, ws.id, today)
    db_session.commit()
    assert created == 0


def test_generate_respects_tombstone(db_session, seed_ws):
    ws = seed_ws["ws"]
    today = date(2026, 7, 18)

    monthly = _template(ws.id, title="Aluguel", day_of_month=10)
    db_session.add(monthly)
    db_session.commit()

    assert RecurringService.generate_due_instances(db_session, ws.id, today) == 1
    db_session.commit()

    # Usuária excluiu a instância do mês: não ressuscita
    tx = db_session.exec(select(Transaction).where(Transaction.workspace_id == ws.id)).one()
    tx.deleted_at = datetime.now(UTC)
    db_session.add(tx)
    db_session.commit()

    assert RecurringService.generate_due_instances(db_session, ws.id, today) == 0
