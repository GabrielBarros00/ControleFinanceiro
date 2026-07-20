from decimal import Decimal
from typing import Any, Dict, List

from app.domain.money import Money
from app.models.transaction import SplitMethod
from app.services.split_service import SplitService


class ItemSplitService:
    """Divisão no nível do item: cada item tem suas shares (mesmo método entre
    elas) e os splits da transação são DERIVADOS da agregação por usuário —
    invariante: sum(shares do item) == valor do item e sum(derivados) == total.
    """

    @staticmethod
    def compute_item_shares(
        item_title: str,
        item_amount: Money,
        shares: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """shares: [{user_id, split_method, input_value}] → [{user_id, amount}].

        Ordena por user_id asc antes de delegar ao SplitService: o resíduo de
        arredondamento cai sempre no mesmo participante, mantendo round-trips
        de edição determinísticos.
        """
        if not shares:
            raise ValueError(f"Item '{item_title}' precisa de ao menos um participante")

        ordered = sorted(shares, key=lambda s: s["user_id"])
        method: SplitMethod = ordered[0]["split_method"]

        # Pré-validação com mensagens PT-BR contextualizadas por item — o
        # SplitService validaria também, mas com mensagens genéricas em inglês
        if method == SplitMethod.percentage:
            total_pct = sum(Decimal(str(s["input_value"])) for s in ordered)
            if total_pct != Decimal("100"):
                raise ValueError(
                    f"Percentuais do item '{item_title}' somam {total_pct} — devem somar 100"
                )
        elif method == SplitMethod.fixed:
            total_fixed = sum(Decimal(str(s["input_value"])) for s in ordered)
            if total_fixed != item_amount.amount:
                raise ValueError(
                    f"Valores fixos do item '{item_title}' somam {total_fixed} — "
                    f"devem ser {item_amount.amount}"
                )

        if method == SplitMethod.equal:
            return SplitService.calculate_splits(
                total_amount=item_amount,
                method=method,
                user_ids=[s["user_id"] for s in ordered],
            )
        return SplitService.calculate_splits(
            total_amount=item_amount,
            method=method,
            input_data=[
                {"user_id": s["user_id"], "value": s["input_value"]} for s in ordered
            ],
        )

    @staticmethod
    def derive_transaction_splits(
        computed_by_item: List[List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        """Agrega as shares calculadas de todos os itens por usuário."""
        totals: Dict[int, Decimal] = {}
        for item_shares in computed_by_item:
            for share in item_shares:
                totals[share["user_id"]] = (
                    totals.get(share["user_id"], Decimal("0")) + share["amount"]
                )
        return [
            {"user_id": user_id, "amount": amount}
            for user_id, amount in sorted(totals.items())
        ]
