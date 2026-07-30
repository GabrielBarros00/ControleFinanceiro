from decimal import Decimal
from datetime import date, datetime, UTC
from sqlmodel import Session, select
from app.models.workspace import Workspace
from app.models.user import User
from app.models.recurring import RecurringIncome
from app.models.income import Income
from app.services.recurring_service import (
    RecurringIncomeService,
    RecurringMaterializationService,
)


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
        user_id=user_id,
        **kw,
    )


def test_generate_due_income_materializes(db_session: Session):
    u, ws = _setup(db_session, "ri1")
    tmpl = _template(ws.id, u.id, category="Salário")
    db_session.add(tmpl)
    db_session.commit()

    created = RecurringIncomeService.generate_due_income(db_session, u.id, date(2026, 7, 15))
    db_session.commit()
    assert created == 1

    incomes = db_session.exec(select(Income).where(Income.user_id == u.id)).all()
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

    assert RecurringIncomeService.generate_due_income(db_session, u.id, date(2026, 7, 15)) == 1
    db_session.commit()
    # Re-rodar no mesmo mês não duplica
    assert RecurringIncomeService.generate_due_income(db_session, u.id, date(2026, 7, 20)) == 0
    db_session.commit()

    incomes = db_session.exec(select(Income).where(Income.user_id == u.id)).all()
    assert len(incomes) == 1


def test_generate_income_conta_mes_inteiro_mesmo_com_data_futura(db_session: Session):
    """Renda é de COMPETÊNCIA: o salário do dia 25 é renda de julho já no dia 10.

    Antes só materializava a partir da data, então a receita do mês aparecia
    zerada até o dia chegar (e sumia ao mover a data para frente).
    """
    u, ws = _setup(db_session, "ri3")
    db_session.add(_template(ws.id, u.id, day_of_month=25))
    db_session.commit()

    assert RecurringIncomeService.generate_due_income(db_session, u.id, date(2026, 7, 10)) == 1
    db_session.commit()

    incomes = db_session.exec(select(Income).where(Income.user_id == u.id)).all()
    assert len(incomes) == 1
    assert incomes[0].billing_month == "2026-07"
    # A data de recebimento continua sendo a real (futura) — é ela que se explica
    # na lista; o mês de competência é que passa a contar.
    assert incomes[0].received_at.date() == date(2026, 7, 25)


def test_generate_due_income_inactive_skipped(db_session: Session):
    u, ws = _setup(db_session, "ri4")
    db_session.add(_template(ws.id, u.id, is_active=False))
    db_session.commit()

    assert RecurringIncomeService.generate_due_income(db_session, u.id, date(2026, 7, 15)) == 0


def test_generate_due_income_tombstone_not_resurrected(db_session: Session):
    u, ws = _setup(db_session, "ri5")
    db_session.add(_template(ws.id, u.id))
    db_session.commit()

    RecurringIncomeService.generate_due_income(db_session, u.id, date(2026, 7, 15))
    db_session.commit()
    inc = db_session.exec(select(Income).where(Income.user_id == u.id)).first()

    # Exclui (tombstone)
    inc.deleted_at = datetime.now(UTC)
    db_session.add(inc)
    db_session.commit()

    # Re-gerar no mesmo mês NÃO ressuscita a instância excluída
    created = RecurringIncomeService.generate_due_income(db_session, u.id, date(2026, 7, 20))
    db_session.commit()
    assert created == 0

    all_rows = db_session.exec(select(Income).where(Income.user_id == u.id)).all()
    assert len(all_rows) == 1
    assert all_rows[0].deleted_at is not None


def test_ensure_current_month_materializes_and_is_idempotent(db_session: Session):
    # Cenário do dono: renda mensal dia 1, começa no 1º do mês → conta no mês
    # corrente sozinha (sem "Lançar pendentes") e não duplica ao recarregar.
    u, ws = _setup(db_session, "ri6")
    db_session.add(_template(ws.id, u.id, day_of_month=1, start_date=date(2026, 7, 1)))
    db_session.commit()

    # A renda tem caminho PRÓPRIO desde o ADR 0021: `ensure_current_month` cuida
    # da despesa do workspace, e a renda pessoal não passa por workspace nenhum.
    assert RecurringMaterializationService.ensure_income_and_commit(
        db_session, u.id, date(2026, 7, 23)
    ) == 1

    # Recarregar a mesma tela (2ª chamada) não duplica
    assert RecurringMaterializationService.ensure_income_and_commit(
        db_session, u.id, date(2026, 7, 25)
    ) == 0

    rows = db_session.exec(select(Income).where(Income.user_id == u.id)).all()
    assert len(rows) == 1


def test_sync_current_month_income_updates_current(db_session: Session):
    u, ws = _setup(db_session, "ri7")
    tmpl = _template(ws.id, u.id, day_of_month=1, start_date=date(2026, 7, 1), base_amount=Decimal("100.00"))
    db_session.add(tmpl)
    db_session.commit()
    RecurringIncomeService.generate_due_income(db_session, u.id, date(2026, 7, 23))
    db_session.commit()

    tmpl.base_amount = Decimal("200.00")
    tmpl.title = "Salário Novo"
    db_session.add(tmpl)
    RecurringIncomeService.sync_current_month_income(db_session, tmpl, date(2026, 7, 23))
    db_session.commit()

    inc = db_session.exec(select(Income).where(Income.recurring_income_id == tmpl.id)).one()
    assert inc.amount == Decimal("200.00")
    assert inc.title == "Salário Novo"


def test_sync_current_month_income_freezes_previous_months(db_session: Session):
    # Editar em agosto não pode alterar o lançamento (fechado) de julho
    u, ws = _setup(db_session, "ri8")
    tmpl = _template(ws.id, u.id, day_of_month=1, start_date=date(2026, 7, 1), base_amount=Decimal("100.00"))
    db_session.add(tmpl)
    db_session.commit()
    RecurringIncomeService.generate_due_income(db_session, u.id, date(2026, 7, 23))
    db_session.commit()

    tmpl.base_amount = Decimal("999.00")
    db_session.add(tmpl)
    RecurringIncomeService.sync_current_month_income(db_session, tmpl, date(2026, 8, 10))
    db_session.commit()

    july = db_session.exec(select(Income).where(Income.billing_month == "2026-07")).one()
    assert july.amount == Decimal("100.00")  # mês fechado permanece congelado
