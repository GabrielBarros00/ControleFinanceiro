from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from typing import List, Dict, Any
from app.domain.dates import add_months
from app.models.financing import AmortizationMethod, AmortizationInstallment

class FinancingService:
    @staticmethod
    def calculate_amortization_schedule(
        total_amount: Decimal,
        interest_rate: Decimal,  # Monthly rate (e.g., 0.01 for 1%)
        installments_count: int,
        start_date: date,
        method: AmortizationMethod
    ) -> List[AmortizationInstallment]:
        schedule = []
        remaining_balance = total_amount
        
        if method == AmortizationMethod.SAC:
            # SAC: Constant Principal Amortization
            principal_amortization = (total_amount / installments_count).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            
            for i in range(1, installments_count + 1):
                interest_amount = (remaining_balance * interest_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                
                # Adjust last installment for rounding
                if i == installments_count:
                    principal_amortization = remaining_balance
                    
                total_installment = principal_amortization + interest_amount
                remaining_balance -= principal_amortization
                
                due_date = add_months(start_date, i)  # mês de calendário
                
                schedule.append(AmortizationInstallment(
                    installment_number=i,
                    due_date=due_date,
                    principal_amount=principal_amortization,
                    interest_amount=interest_amount,
                    total_amount=total_installment,
                    remaining_balance=max(Decimal("0.00"), remaining_balance)
                ))
                
        elif method == AmortizationMethod.PRICE:
            # PRICE: Constant Total Installment
            # PMT = P * [i(1+i)^n] / [(1+i)^n - 1]
            if interest_rate > 0:
                factor = (1 + interest_rate) ** installments_count
                pmt = (total_amount * (interest_rate * factor) / (factor - 1)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            else:
                pmt = (total_amount / installments_count).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                
            for i in range(1, installments_count + 1):
                interest_amount = (remaining_balance * interest_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                
                # Adjust last installment for rounding
                if i == installments_count:
                    principal_amortization = remaining_balance
                    total_installment = principal_amortization + interest_amount
                else:
                    principal_amortization = pmt - interest_amount
                    total_installment = pmt
                    
                remaining_balance -= principal_amortization
                
                due_date = add_months(start_date, i)  # mês de calendário
                
                schedule.append(AmortizationInstallment(
                    installment_number=i,
                    due_date=due_date,
                    principal_amount=principal_amortization,
                    interest_amount=interest_amount,
                    total_amount=total_installment,
                    remaining_balance=max(Decimal("0.00"), remaining_balance)
                ))
                
        return schedule

    @staticmethod
    def simulate_early_settlement(
        remaining_installments: List[AmortizationInstallment],
        settlement_date: date,
        monthly_interest_rate: Decimal
    ) -> Dict[str, Any]:
        """
        Simulates the 'quitar' action (early settlement).
        Calculates the Present Value (PV) of future installments.
        """
        total_to_pay = Decimal("0.00")
        total_original_value = Decimal("0.00")
        total_savings = Decimal("0.00")
        
        for inst in remaining_installments:
            total_original_value += inst.total_amount
            
            # Simplified PV calculation for each installment
            # PV = FV / (1 + i)^n
            # n is the number of months between settlement and due_date
            months_early = max(0, (inst.due_date.year - settlement_date.year) * 12 + (inst.due_date.month - settlement_date.month))
            
            pv = (inst.total_amount / ((1 + monthly_interest_rate) ** months_early)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            total_to_pay += pv
            
        total_savings = total_original_value - total_to_pay
        
        return {
            "total_to_pay": total_to_pay,
            "original_value": total_original_value,
            "savings": total_savings,
            "installments_settled": len(remaining_installments)
        }
