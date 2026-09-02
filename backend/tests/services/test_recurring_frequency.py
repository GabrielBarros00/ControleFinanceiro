"""Recorrência semanal/mensal/anual: ocorrências e materialização de instâncias."""
from datetime import date, datetime, UTC
from decimal import Decimal

from sqlmodel import select

from app.models.recurring import RecurringExpense, RecurrenceFrequency
from app.models.transaction import Transaction, TransactionStatus
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

    created = RecurringService.generate_due_instances(db_session, ws.id, today, horizonte_meses=0)
    db_session.commit()
    # Mês INTEIRO: aluguel 10/07 + feira 06, 13, 20 e 27/07
    assert created == 5

    txs = db_session.exec(
        select(Transaction).where(Transaction.workspace_id == ws.id)
    ).all()
    assert len(txs) == 5
    titles = sorted(tx.title for tx in txs)
    assert titles == ["Aluguel", "Feira", "Feira", "Feira", "Feira"]

    # O que já venceu nasce confirmado (entra nos totais); o que ainda vem no mês
    # nasce pendente (aparece como "a pagar" sem mexer em nenhum total realizado).
    confirmed = {tx.occurrence_date for tx in txs if tx.status == TransactionStatus.confirmed}
    pending = {tx.occurrence_date for tx in txs if tx.status == TransactionStatus.pending}
    assert confirmed == {date(2026, 7, 10), date(2026, 7, 6), date(2026, 7, 13)}
    assert pending == {date(2026, 7, 20), date(2026, 7, 27)}

    # Idempotente
    created = RecurringService.generate_due_instances(db_session, ws.id, today, horizonte_meses=0)
    db_session.commit()
    assert created == 0


def test_pendente_vira_confirmada_quando_a_data_chega(db_session, seed_ws):
    """A parcela futura nasce `pending` e é promovida a `confirmed` no dia — sem
    isso a conta do fim do mês ficaria fora dos totais realizados para sempre."""
    ws = seed_ws["ws"]
    db_session.add(_template(ws.id, title="Aluguel", day_of_month=25))
    db_session.commit()

    RecurringService.generate_due_instances(db_session, ws.id, date(2026, 7, 10), horizonte_meses=0)
    db_session.commit()
    tx = db_session.exec(select(Transaction).where(Transaction.workspace_id == ws.id)).one()
    assert tx.status == TransactionStatus.pending

    # Nada a promover antes da data
    assert RecurringService.promote_due_instances(db_session, ws.id, date(2026, 7, 24)) == 0
    db_session.commit()

    assert RecurringService.promote_due_instances(db_session, ws.id, date(2026, 7, 25)) == 1
    db_session.commit()
    db_session.refresh(tx)
    assert tx.status == TransactionStatus.confirmed


def test_generate_respects_tombstone(db_session, seed_ws):
    ws = seed_ws["ws"]
    today = date(2026, 7, 18)

    monthly = _template(ws.id, title="Aluguel", day_of_month=10)
    db_session.add(monthly)
    db_session.commit()

    assert RecurringService.generate_due_instances(db_session, ws.id, today, horizonte_meses=0) == 1
    db_session.commit()

    # Usuária excluiu a instância do mês: não ressuscita
    tx = db_session.exec(select(Transaction).where(Transaction.workspace_id == ws.id)).one()
    tx.deleted_at = datetime.now(UTC)
    db_session.add(tx)
    db_session.commit()

    assert RecurringService.generate_due_instances(db_session, ws.id, today, horizonte_meses=0) == 0
