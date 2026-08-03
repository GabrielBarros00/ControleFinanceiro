from sqlmodel import Session
from datetime import datetime, date
from decimal import Decimal
from app.models.transaction import Transaction
from app.models.recurring import RecurringExpense
from app.models.estimate import MonthlyEstimate
from app.services.forecast_service import ForecastService

from unittest.mock import patch

def test_forecast_calculation(db_session: Session, seed_ws):
    workspace_id = seed_ws["ws"].id
    target_month = date(2026, 5, 1)
    
    # Patch onde é USADO (importado), não onde é definido. O serviço passou a
    # chamar `today_local()` — o dia de calendário do fuso do app —, então um
    # mock em `date.today` não o alcança mais.
    with patch("app.services.forecast_service.today_local", return_value=date(2026, 5, 6)):

        # 1. Setup: 3 transactions in May (Total 300)
        t1 = Transaction(title="T1", total_amount=Decimal("100.00"), transaction_date=datetime(2026, 5, 1), workspace_id=workspace_id)
        t2 = Transaction(title="T2", total_amount=100.00, transaction_date=datetime(2026, 5, 2), workspace_id=workspace_id)
        t3 = Transaction(title="T3", total_amount=100.00, transaction_date=datetime(2026, 5, 3), workspace_id=workspace_id)
        db_session.add_all([t1, t2, t3])
        
        # 2. Setup: 1 recurring expense on May 15th (1000.00)
        r1 = RecurringExpense(title="Rent", base_amount=1000.00, day_of_month=15, workspace_id=workspace_id, is_active=True)
        db_session.add(r1)
        
        # 3. Setup: Monthly Budget (2500.00)
        e1 = MonthlyEstimate(category="All", amount=2500.00, month="2026-05", workspace_id=workspace_id, user_id=seed_ws["user"].id)
        db_session.add(e1)
        
        db_session.commit()
        
        # Act
        projection = ForecastService.get_monthly_projection(db_session, workspace_id, target_month)
        
        # Assert
        assert projection["actual_spent"] == Decimal("300.00")
        # Daily avg = 300 / 6 (today is 6th) = 50.00
        assert projection["daily_average"] == Decimal("50.00")
        
        # Projected EOM = 300 + (50 * 25 remaining days) + 1000 (rent on 15th)
        # 300 + 1250 + 1000 = 2550
        assert projection["projected_eom"] == Decimal("2550.00")
        assert projection["is_over_budget"] is True

def test_tendencia_ignora_fixos_ja_lancados(db_session: Session, seed_ws):
    """Custo fixo não pode entrar na média diária e ser extrapolado.

    O aluguel cai no dia 1 e não se repete no mês — mas a tendência era calculada
    sobre TUDO que já foi gasto, então no dia 6 ele virava média de 510/dia e a
    projeção somava mais 12.750 de gasto que não existe. Além de o fixo já estar
    contado duas vezes (no realizado e em `fixed_costs_pending`, quando ainda não
    venceu). Só o gasto VARIÁVEL é tendência.
    """
    workspace_id = seed_ws["ws"].id
    target_month = date(2026, 5, 1)

    # `today_local()` no lugar de `date.today()`: o serviço passou a usar o dia
    # de calendário do fuso do APP, e um mock em `date` não o alcança mais.
    with patch("app.services.forecast_service.today_local", return_value=date(2026, 5, 6)):

        aluguel = RecurringExpense(
            title="Aluguel", base_amount=Decimal("3000.00"), day_of_month=1,
            workspace_id=workspace_id, is_active=True,
        )
        db_session.add(aluguel)
        db_session.flush()

        # Instância já materializada do fixo + uma compra avulsa de 60
        db_session.add_all([
            Transaction(
                title="Aluguel", total_amount=Decimal("3000.00"),
                transaction_date=datetime(2026, 5, 1), billing_month="2026-05",
                workspace_id=workspace_id, recurring_expense_id=aluguel.id,
            ),
            Transaction(
                title="Padaria", total_amount=Decimal("60.00"),
                transaction_date=datetime(2026, 5, 2), billing_month="2026-05",
                workspace_id=workspace_id,
            ),
        ])
        db_session.commit()

        projection = ForecastService.get_monthly_projection(db_session, workspace_id, target_month)

        # Realizado continua sendo tudo que saiu
        assert projection["actual_spent"] == Decimal("3060.00")
        # Tendência só sobre os 60 variáveis: 60 / 6 dias = 10/dia
        assert projection["daily_average"] == Decimal("10.00")
        # O aluguel já venceu (dia 1 <= hoje), então não é fixo pendente
        assert projection["fixed_costs_pending"] == Decimal("0.00")
        # 3060 + 10 × 25 dias restantes = 3310 (e não 15.810 com o aluguel na média)
        assert projection["projected_eom"] == Decimal("3310.00")


def test_tendencia_ignora_parcelas(db_session: Session, seed_ws):
    """Parcela de compra parcelada também não é tendência: a do mês que vem já é
    uma linha do mês que vem, não algo a prever pela média diária."""
    workspace_id = seed_ws["ws"].id
    target_month = date(2026, 5, 1)

    # `today_local()` no lugar de `date.today()`: o serviço passou a usar o dia
    # de calendário do fuso do APP, e um mock em `date` não o alcança mais.
    with patch("app.services.forecast_service.today_local", return_value=date(2026, 5, 6)):

        db_session.add(Transaction(
            title="Geladeira (1/10)", total_amount=Decimal("500.00"),
            transaction_date=datetime(2026, 5, 2), billing_month="2026-05",
            workspace_id=workspace_id,
            installment_group_id="grupo-1", installment_no=1, installments_of=10,
        ))
        db_session.commit()

        projection = ForecastService.get_monthly_projection(db_session, workspace_id, target_month)

        assert projection["actual_spent"] == Decimal("500.00")
        assert projection["daily_average"] == Decimal("0.00")
        assert projection["projected_eom"] == Decimal("500.00")


def test_forecast_past_month(db_session: Session, seed_ws):
    workspace_id = seed_ws["ws"].id
    target_month = date(2026, 4, 1) # April (Past)
    
    # `today_local()` no lugar de `date.today()`: o serviço passou a usar o dia
    # de calendário do fuso do APP, e um mock em `date` não o alcança mais.
    with patch("app.services.forecast_service.today_local", return_value=date(2026, 5, 6)):
        
        # 400 spent in April
        t1 = Transaction(title="T1", total_amount=Decimal("400.00"), transaction_date=datetime(2026, 4, 10), workspace_id=workspace_id)
        db_session.add(t1)
        db_session.commit()
        
        projection = ForecastService.get_monthly_projection(db_session, workspace_id, target_month)
        
        assert projection["actual_spent"] == Decimal("400.00")
        assert projection["remaining_days"] == 0
        assert projection["fixed_costs_pending"] == 0

def test_forecast_future_month(db_session: Session, seed_ws):
    workspace_id = seed_ws["ws"].id
    target_month = date(2026, 6, 1) # June (Future)
    
    # `today_local()` no lugar de `date.today()`: o serviço passou a usar o dia
    # de calendário do fuso do APP, e um mock em `date` não o alcança mais.
    with patch("app.services.forecast_service.today_local", return_value=date(2026, 5, 6)):
        
        # Recurring expense in future month (should all be pending)
        r1 = RecurringExpense(title="Rent", base_amount=1000.00, day_of_month=15, workspace_id=workspace_id, is_active=True)
        db_session.add(r1)
        db_session.commit()
        
        projection = ForecastService.get_monthly_projection(db_session, workspace_id, target_month)
        
        assert projection["actual_spent"] == Decimal("0.00")
        assert projection["remaining_days"] == 30 # June has 30 days
        assert projection["fixed_costs_pending"] == Decimal("1000.00")