from decimal import Decimal
from datetime import date, datetime, UTC
from sqlmodel import Session, select
from app.models.workspace import Workspace
from app.models.user import User
from app.models.recurring import RecurringIncome
from app.models.income import Income
from app.services.recurring_service import RecurringIncomeService


def _setup(db_session: Session, tag: str):
    u = User(name="Gabriel", email=f"{tag}@t.com", password_hash="h")
    ws = Workspace(name=f"WS-{tag}")
    db_session.add_all([u, ws])
    db_session.flush()
    return u, ws


def _template(ws_id: int, user_id: int, **kw) -> RecurringIncome:
    return RecurringIncome(
        title=kw.pop("title", "Salário"),
        base_amount=kw.pop("base_amount", Decimal("5000.00")),
        day_of_month=kw.pop("day_of_month", 10),
        workspace_id=ws_id,
        user_id=user_id,
        **kw,
    )


def test_generate_due_income_materializes(db_session: Session):
    u, ws = _setup(db_session, "ri1")
    tmpl = _template(ws.id, u.id, category="Salário")
    db_session.add(tmpl)
    db_session.commit()

    created = RecurringIncomeService.generate_due_income(db_session, ws.id, date(2026, 7, 15))
    db_session.commit()
    assert created == 1

    incomes = db_session.exec(select(Income).where(Income.workspace_id == ws.id)).all()
    assert len(incomes) == 1
    inc = incomes[0]
    assert inc.title == "Salário"
    assert inc.amount == Decimal("5000.00")
    assert inc.category == "Salário"
    assert inc.recurring_income_id == tmpl.id
    assert inc.billing_month == "2026-07"
    assert inc.user_id == u.id


def test_generate_due_income_idempotent(db_session: Session):
    u, ws = _setup(db_session, "ri2")
    db_session.add(_template(ws.id, u.id))
    db_session.commit()

    assert RecurringIncomeService.generate_due_income(db_session, ws.id, date(2026, 7, 15)) == 1
    db_session.commit()
    # Re-rodar no mesmo mês não duplica
    assert RecurringIncomeService.generate_due_income(db_session, ws.id, date(2026, 7, 20)) == 0
    db_session.commit()

    incomes = db_session.exec(select(Income).where(Income.workspace_id == ws.id)).all()
    assert len(incomes) == 1


def test_generate_due_income_not_yet_due(db_session: Session):
    u, ws = _setup(db_session, "ri3")
    db_session.add(_template(ws.id, u.id, day_of_month=25))
    db_session.commit()

    # Hoje é dia 10, vencimento dia 25 → ainda não materializa
    assert RecurringIncomeService.generate_due_income(db_session, ws.id, date(2026, 7, 10)) == 0
    assert db_session.exec(select(Income).where(Income.workspace_id == ws.id)).all() == []


def test_generate_due_income_inactive_skipped(db_session: Session):
    u, ws = _setup(db_session, "ri4")
    db_session.add(_template(ws.id, u.id, is_active=False))
    db_session.commit()

    assert RecurringIncomeService.generate_due_income(db_session, ws.id, date(2026, 7, 15)) == 0


def test_generate_due_income_tombstone_not_resurrected(db_session: Session):
    u, ws = _setup(db_session, "ri5")
    db_session.add(_template(ws.id, u.id))
    db_session.commit()

    RecurringIncomeService.generate_due_income(db_session, ws.id, date(2026, 7, 15))
    db_session.commit()
    inc = db_session.exec(select(Income).where(Income.workspace_id == ws.id)).first()

    # Exclui (tombstone)
    inc.deleted_at = datetime.now(UTC)
    db_session.add(inc)
    db_session.commit()

    # Re-gerar no mesmo mês NÃO ressuscita a instância excluída
    created = RecurringIncomeService.generate_due_income(db_session, ws.id, date(2026, 7, 20))
    db_session.commit()
    assert created == 0

    all_rows = db_session.exec(select(Income).where(Income.workspace_id == ws.id)).all()
    assert len(all_rows) == 1
    assert all_rows[0].deleted_at is not None
