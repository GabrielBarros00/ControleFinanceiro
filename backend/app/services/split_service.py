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
                raise ValueError("Divisão igual exige a lista de participantes")

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
                raise ValueError("Divisão por porcentagem exige os percentuais de cada participante")

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
                raise ValueError("Divisão por valor fixo exige o valor de cada participante")
            
            # Validação manual: soma dos valores fixos deve ser igual ao total
            total_fixed = sum(Decimal(str(item["value"])) for item in input_data)
            if total_fixed != total_amount.amount:
                raise ValueError(f"A soma da divisão ({total_fixed}) difere do total ({total_amount.amount})")
            
            for item in input_data:
                results.append({
                    "user_id": item["user_id"],
                    "amount": Decimal(str(item["value"]))
                })
        
        return results
