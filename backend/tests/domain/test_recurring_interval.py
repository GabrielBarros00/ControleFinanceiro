from datetime import date
from decimal import Decimal
from sqlmodel import Session, select

from app.models.recurring import RecurringExpense, RecurringIncome, RecurrenceFrequency
from app.models.workspace import Workspace
from app.models.user import User
from app.models.income import Income
from app.services.recurring_service import RecurringService, RecurringIncomeService


def _exp(**kw) -> RecurringExpense:
    return RecurringExpense(
        title="x",
        base_amount=Decimal("10.00"),
        workspace_id=1,
        day_of_month=kw.pop("day_of_month", 1),
        **kw,
    )


def test_daily_every_3_days():
    t = _exp(frequency=RecurrenceFrequency.daily, interval=3, start_date=date(2026, 7, 1))
    occ = RecurringService.occurrences_in_month(t, 2026, 7)
    assert occ == [date(2026, 7, d) for d in (1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31)]


def test_daily_interval_keeps_phase_across_months():
    # âncora 30/07, a cada 3 dias → agosto continua a fase (02, 05, 08, ...)
    t = _exp(frequency=RecurrenceFrequency.daily, interval=3, start_date=date(2026, 7, 30))
    occ_aug = RecurringService.occurrences_in_month(t, 2026, 8)
    assert occ_aug[0] == date(2026, 8, 2)
    assert occ_aug[1] == date(2026, 8, 5)


def test_weekly_every_2_weeks():
    # âncora quarta 01/07; a cada 2 semanas → 01, 15, 29
    t = _exp(frequency=RecurrenceFrequency.weekly, interval=2, start_date=date(2026, 7, 1))
    occ = RecurringService.occurrences_in_month(t, 2026, 7)
    assert occ == [date(2026, 7, 1), date(2026, 7, 15), date(2026, 7, 29)]


def test_monthly_every_2_months_alignment():
    # âncora 10/01, a cada 2 meses → jan, mar, mai, jul ...
    t = _exp(frequency=RecurrenceFrequency.monthly, interval=2, start_date=date(2026, 1, 10))
    assert RecurringService.occurrences_in_month(t, 2026, 1) == [date(2026, 1, 10)]
    assert RecurringService.occurrences_in_month(t, 2026, 2) == []  # fora do ciclo
    assert RecurringService.occurrences_in_month(t, 2026, 3) == [date(2026, 3, 10)]
    assert RecurringService.occurrences_in_month(t, 2026, 7) == [date(2026, 7, 10)]


def test_monthly_interval_day_clamped_to_month_end():
    # âncora 31/01, a cada 2 meses → mar (dia 31 existe); mês âncora tem 31
    t = _exp(frequency=RecurrenceFrequency.monthly, interval=2, start_date=date(2026, 1, 31))
    assert RecurringService.occurrences_in_month(t, 2026, 1) == [date(2026, 1, 31)]
    assert RecurringService.occurrences_in_month(t, 2026, 3) == [date(2026, 3, 31)]


def test_yearly_every_2_years():
    t = _exp(frequency=RecurrenceFrequency.yearly, interval=2, start_date=date(2026, 3, 15))
    assert RecurringService.occurrences_in_month(t, 2026, 3) == [date(2026, 3, 15)]
    assert RecurringService.occurrences_in_month(t, 2027, 3) == []   # fora do ciclo
    assert RecurringService.occurrences_in_month(t, 2028, 3) == [date(2028, 3, 15)]
    assert RecurringService.occurrences_in_month(t, 2026, 4) == []   # mês errado


def test_interval_before_anchor_is_empty():
    t = _exp(frequency=RecurrenceFrequency.daily, interval=5, start_date=date(2026, 7, 10))
    assert RecurringService.occurrences_in_month(t, 2026, 6) == []


def test_interval_falls_back_to_created_at_when_no_start_date():
    # start_date None → ancora em created_at (mês da criação é offset 0 = alinhado)
    t = _exp(frequency=RecurrenceFrequency.monthly, interval=3)
    cm = t.created_at
    occ = RecurringService.occurrences_in_month(t, cm.year, cm.month)
    assert len(occ) == 1


def test_interval_one_is_unchanged_legacy():
    # interval == 1 mantém o comportamento phase-free (todo dia no diário)
    t = _exp(frequency=RecurrenceFrequency.daily, interval=1)
    occ = RecurringService.occurrences_in_month(t, 2026, 2)
    assert len(occ) == 28  # fev/2026


def test_generate_income_respects_interval(db_session: Session):
    u = User(name="G", email="ri_int@t.com", password_hash="h")
    ws = Workspace(name="WS-int")
    db_session.add_all([u, ws])
    db_session.flush()
    tmpl = RecurringIncome(
        title="Bônus", base_amount=Decimal("100.00"),
        workspace_id=ws.id, user_id=u.id,
        frequency=RecurrenceFrequency.monthly, interval=2,
        start_date=date(2026, 1, 10), day_of_month=10,
    )
    db_session.add(tmpl)
    db_session.commit()

    # fevereiro está fora do ciclo (a cada 2 meses a partir de janeiro)
    assert RecurringIncomeService.generate_due_income(db_session, ws.id, date(2026, 2, 15)) == 0
    db_session.commit()
    # março está no ciclo
    assert RecurringIncomeService.generate_due_income(db_session, ws.id, date(2026, 3, 15)) == 1
    db_session.commit()

    incomes = db_session.exec(select(Income).where(Income.workspace_id == ws.id)).all()
    assert len(incomes) == 1
    assert incomes[0].billing_month == "2026-03"
