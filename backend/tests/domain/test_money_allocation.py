"""Testes de propriedade da alocação monetária (ADR 0001).

Invariantes para qualquer divisão com total >= 0:
1. A soma das parcelas é EXATAMENTE o total.
2. Nenhuma parcela é negativa.
3. As parcelas diferem entre si em no máximo 1 centavo (divisão igual).
4. O resultado independe da ordem do payload (SplitService ordena por user_id).
"""
import random
from decimal import Decimal

import pytest

from app.domain.money import Money
from app.models.transaction import SplitMethod
from app.services.split_service import SplitService

CENT = Decimal("0.01")


@pytest.mark.parametrize("total_cents", list(range(1, 201)) + [999, 1000, 10001, 333333])
@pytest.mark.parametrize("parts", [1, 2, 3, 7, 10, 15, 40])
def test_split_equal_propriedades(total_cents: int, parts: int):
    total = Money(Decimal(total_cents) / 100)
    splits = total.split_equal(parts)

    assert len(splits) == parts
    assert sum(s.amount for s in splits) == total.amount
    assert all(s.amount >= 0 for s in splits), (
        f"parcela negativa em {total.amount}/{parts}: {[str(s.amount) for s in splits]}"
    )
    assert max(s.amount for s in splits) - min(s.amount for s in splits) <= CENT


def test_fin001_cinco_centavos_entre_dez():
    """Caso exato do defeito FIN-001: R$ 0,05 entre 10 pessoas."""
    splits = Money("0.05").split_equal(10)
    amounts = [s.amount for s in splits]
    assert amounts == [CENT] * 5 + [Decimal("0.00")] * 5
    assert sum(amounts) == Decimal("0.05")


@pytest.mark.parametrize("percentages", [
    ["33.33", "33.33", "33.34"],
    ["0.01", "99.99"],
    ["50", "25", "25"],
    ["10", "10", "10", "10", "10", "10", "10", "10", "10", "10"],
    ["1", "2", "3", "4", "90"],
    ["16.67", "16.67", "16.67", "16.67", "16.66", "16.66"],
])
@pytest.mark.parametrize("total", ["0.01", "0.05", "1.00", "10.00", "99.99", "1234.56"])
def test_split_percentage_propriedades(total: str, percentages: list):
    money = Money(total)
    splits = money.split_by_percentages([Decimal(p) for p in percentages])

    assert sum(s.amount for s in splits) == money.amount
    assert all(s.amount >= 0 for s in splits)
    # Cada parcela fica a menos de 1 centavo da cota exata
    for pct, part in zip(percentages, splits):
        exact = money.amount * Decimal(pct) / 100
        assert abs(part.amount - exact) < CENT


@pytest.mark.parametrize("total", ["0.05", "0.07", "100.00", "33.33"])
def test_split_service_equal_independe_da_ordem(total: str):
    """Embaralhar user_ids não muda quem recebe o centavo extra."""
    user_ids = [5, 1, 9, 3, 7, 2, 8]
    reference = {
        r["user_id"]: r["amount"]
        for r in SplitService.calculate_splits(
            Money(total), SplitMethod.equal, user_ids=sorted(user_ids)
        )
    }
    rng = random.Random(42)
    for _ in range(5):
        shuffled = user_ids[:]
        rng.shuffle(shuffled)
        result = {
            r["user_id"]: r["amount"]
            for r in SplitService.calculate_splits(
                Money(total), SplitMethod.equal, user_ids=shuffled
            )
        }
        assert result == reference


def test_split_service_percentage_independe_da_ordem():
    entries = [
        {"user_id": 4, "value": Decimal("33.33")},
        {"user_id": 1, "value": Decimal("33.33")},
        {"user_id": 2, "value": Decimal("33.34")},
    ]
    reference = {
        r["user_id"]: r["amount"]
        for r in SplitService.calculate_splits(
            Money("10.00"), SplitMethod.percentage, input_data=entries
        )
    }
    result = {
        r["user_id"]: r["amount"]
        for r in SplitService.calculate_splits(
            Money("10.00"), SplitMethod.percentage, input_data=list(reversed(entries))
        )
    }
    assert result == reference
    assert sum(result.values()) == Decimal("10.00")
