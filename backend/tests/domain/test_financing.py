from decimal import Decimal
from datetime import date
from app.services.financing_service import FinancingService
from app.models.financing import AmortizationMethod

def test_sac_amortization_math():
    total = Decimal("1000.00")
    rate = Decimal("0.01") # 1% month
    count = 10
    start = date(2026, 5, 1)
    
    schedule = FinancingService.calculate_amortization_schedule(
        total, rate, count, start, AmortizationMethod.SAC
    )
    
    assert len(schedule) == 10
    # SAC principal is constant: 1000 / 10 = 100
    assert schedule[0].principal_amount == Decimal("100.00")
    assert schedule[0].interest_amount == Decimal("10.00") # 1% of 1000
    assert schedule[0].total_amount == Decimal("110.00")
    
    # Last installment
    assert schedule[-1].principal_amount == Decimal("100.00")
    assert schedule[-1].remaining_balance == Decimal("0.00")
    
    # Sum of principals must be total
    assert sum(inst.principal_amount for inst in schedule) == total

def test_price_amortization_math():
    total = Decimal("1000.00")
    rate = Decimal("0.01")
    count = 10
    start = date(2026, 5, 1)
    
    schedule = FinancingService.calculate_amortization_schedule(
        total, rate, count, start, AmortizationMethod.PRICE
    )
    
    assert len(schedule) == 10
    # Price total installment is constant (approx 105.58)
    # Check if all (except last) are roughly equal
    pmt = schedule[0].total_amount
    for inst in schedule[:-1]:
        assert inst.total_amount == pmt
    
    # Sum of principals must be total
    assert sum(inst.principal_amount for inst in schedule) == total
    assert schedule[-1].remaining_balance == Decimal("0.00")

def test_due_dates_por_mes_de_calendario():
    # start 31/jan: parcelas caem no mês de calendário, não a cada 30 dias
    schedule = FinancingService.calculate_amortization_schedule(
        Decimal("900.00"), Decimal("0.01"), 3, date(2026, 1, 31), AmortizationMethod.SAC
    )
    due = [inst.due_date for inst in schedule]
    # +1 mês de 31/jan = 28/fev (limitado); +2 = 31/mar; +3 = 30/abr
    assert due == [date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]
    # cada parcela é exatamente um mês após a anterior (nunca 30 dias fixos)
    assert due[1].month == 3 and due[2].month == 4


def test_early_settlement_simulation():
    total = Decimal("1000.00")
    rate = Decimal("0.01")
    count = 10
    start = date(2026, 5, 1)
    
    schedule = FinancingService.calculate_amortization_schedule(
        total, rate, count, start, AmortizationMethod.PRICE
    )
    
    # Simulate settling last 5 installments today (2026-05-01)
    remaining = schedule[5:]
    simulation = FinancingService.simulate_early_settlement(
        remaining, date(2026, 5, 1), rate
    )
    
    assert simulation["installments_settled"] == 5
    assert simulation["total_to_pay"] < simulation["original_value"]
    assert simulation["savings"] > 0
    print(f"Savings: {simulation['savings']}")
