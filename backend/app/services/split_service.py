from decimal import Decimal
from typing import List, Dict, Optional, Any
from app.domain.money import Money
from app.models.transaction import SplitMethod

class SplitService:
    @staticmethod
    def calculate_splits(
        total_amount: Money,
        method: SplitMethod,
        user_ids: Optional[List[int]] = None,
        input_data: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Calcula a divisão de uma transação entre usuários.
        Retorna uma lista de dicionários com 'user_id' e 'amount'.
        """
        results = []

        if method == SplitMethod.equal:
            if not user_ids:
                raise ValueError("user_ids is required for equal split")

            # Ordem estável por user_id: o centavo extra cai sempre nos
            # mesmos participantes, independente da ordem do payload (ADR 0001)
            ordered_ids = sorted(user_ids)
            money_splits = total_amount.split_equal(len(ordered_ids))
            for idx, user_id in enumerate(ordered_ids):
                results.append({
                    "user_id": user_id,
                    "amount": money_splits[idx].amount
                })

        elif method == SplitMethod.percentage:
            if not input_data:
                raise ValueError("input_data is required for percentage split")

            ordered = sorted(input_data, key=lambda item: item["user_id"])
            percentages = [Decimal(str(item["value"])) for item in ordered]
            money_splits = total_amount.split_by_percentages(percentages)

            for idx, item in enumerate(ordered):
                results.append({
                    "user_id": item["user_id"],
                    "amount": money_splits[idx].amount
                })

        elif method == SplitMethod.fixed:
            if not input_data:
                raise ValueError("input_data is required for fixed split")
            
            # Validação manual: soma dos valores fixos deve ser igual ao total
            total_fixed = sum(Decimal(str(item["value"])) for item in input_data)
            if total_fixed != total_amount.amount:
                raise ValueError(f"Sum of splits must equal total amount ({total_amount.amount}). Current sum: {total_fixed}")
            
            for item in input_data:
                results.append({
                    "user_id": item["user_id"],
                    "amount": Decimal(str(item["value"]))
                })
        
        return results
