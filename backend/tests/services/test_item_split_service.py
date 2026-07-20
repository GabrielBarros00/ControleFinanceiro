import random
from decimal import Decimal

import pytest

from app.domain.money import Money
from app.models.transaction import SplitMethod
from app.services.item_split_service import ItemSplitService


def _share(user_id, method=SplitMethod.equal, value="0"):
    return {"user_id": user_id, "split_method": method, "input_value": Decimal(value)}


def test_equal_residue_deterministic_by_user_id():
    # 0.10 / 3: resíduo de 1 centavo cai no MENOR user_id (ADR 0001:
    # resto aos primeiros na ordem asc), independente da ordem de entrada
    shares = [_share(3), _share(1), _share(2)]
    result = ItemSplitService.compute_item_shares("Bala", Money(Decimal("0.10")), shares)
    assert [(r["user_id"], r["amount"]) for r in result] == [
        (1, Decimal("0.04")),
        (2, Decimal("0.03")),
        (3, Decimal("0.03")),
    ]


def test_percentage_shares():
    shares = [
        _share(1, SplitMethod.percentage, "33.33"),
        _share(2, SplitMethod.percentage, "33.33"),
        _share(3, SplitMethod.percentage, "33.34"),
    ]
    result = ItemSplitService.compute_item_shares("Rodizio", Money(Decimal("100.00")), shares)
    assert sum(r["amount"] for r in result) == Decimal("100.00")


def test_percentage_must_sum_100():
    shares = [
        _share(1, SplitMethod.percentage, "50"),
        _share(2, SplitMethod.percentage, "30"),
    ]
    with pytest.raises(ValueError, match="Percentuais do item 'Pizza' somam 80"):
        ItemSplitService.compute_item_shares("Pizza", Money(Decimal("60.00")), shares)


def test_fixed_must_match_item_amount():
    shares = [
        _share(1, SplitMethod.fixed, "10.00"),
        _share(2, SplitMethod.fixed, "15.00"),
    ]
    with pytest.raises(ValueError, match="Valores fixos do item 'Suco' somam 25.00"):
        ItemSplitService.compute_item_shares("Suco", Money(Decimal("30.00")), shares)


def test_fixed_ok():
    shares = [
        _share(2, SplitMethod.fixed, "20.00"),
        _share(1, SplitMethod.fixed, "10.00"),
    ]
    result = ItemSplitService.compute_item_shares("Carne", Money(Decimal("30.00")), shares)
    assert {(r["user_id"], r["amount"]) for r in result} == {
        (1, Decimal("10.00")),
        (2, Decimal("20.00")),
    }


def test_empty_shares_rejected():
    with pytest.raises(ValueError, match="ao menos um participante"):
        ItemSplitService.compute_item_shares("Vazio", Money(Decimal("10.00")), [])


def test_derive_aggregates_per_user():
    computed_by_item = [
        [{"user_id": 1, "amount": Decimal("30.00")}, {"user_id": 2, "amount": Decimal("30.00")}],
        [{"user_id": 2, "amount": Decimal("30.00")}],
    ]
    derived = ItemSplitService.derive_transaction_splits(computed_by_item)
    assert derived == [
        {"user_id": 1, "amount": Decimal("30.00")},
        {"user_id": 2, "amount": Decimal("60.00")},
    ]


def test_property_derived_always_sums_to_items_total():
    """50 combinações aleatórias: a soma dos splits derivados é SEMPRE a soma
    dos itens — nenhum centavo se perde no arredondamento."""
    rng = random.Random(42)
    for _ in range(50):
        n_items = rng.randint(1, 5)
        computed_by_item = []
        expected_total = Decimal("0")
        for i in range(n_items):
            amount = Decimal(rng.randint(1, 99999)) / 100  # 0.01 a 999.99
            expected_total += amount
            users = rng.sample(range(1, 8), rng.randint(1, 5))
            method = rng.choice([SplitMethod.equal, SplitMethod.percentage, SplitMethod.fixed])
            if method == SplitMethod.equal:
                shares = [_share(u) for u in users]
            elif method == SplitMethod.percentage:
                # percentuais inteiros que somam 100
                cuts = sorted(rng.sample(range(1, 100), len(users) - 1)) if len(users) > 1 else []
                bounds = [0] + cuts + [100]
                pcts = [bounds[j + 1] - bounds[j] for j in range(len(users))]
                shares = [
                    _share(u, SplitMethod.percentage, str(p)) for u, p in zip(users, pcts)
                ]
            else:
                # valores fixos em centavos que somam o item (no máximo um
                # participante por centavo disponível)
                total_cents = int(amount * 100)
                k = min(len(users), total_cents)
                users = users[:k]
                cuts = sorted(rng.sample(range(1, total_cents), k - 1)) if k > 1 else []
                bounds = [0] + cuts + [total_cents]
                vals = [Decimal(bounds[j + 1] - bounds[j]) / 100 for j in range(k)]
                shares = [
                    _share(u, SplitMethod.fixed, str(v)) for u, v in zip(users, vals)
                ]
            computed_by_item.append(
                ItemSplitService.compute_item_shares(f"Item {i}", Money(amount), shares)
            )
        derived = ItemSplitService.derive_transaction_splits(computed_by_item)
        assert sum(d["amount"] for d in derived) == expected_total
