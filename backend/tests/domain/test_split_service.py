import pytest
from decimal import Decimal
from app.domain.money import Money
from app.models.transaction import SplitMethod
from app.services.split_service import SplitService

def test_calculate_splits_equal():
    total = Money("100.00")
    user_ids = [1, 2, 3]
    
    splits = SplitService.calculate_splits(
        total_amount=total,
        user_ids=user_ids,
        method=SplitMethod.equal
    )
    
    assert len(splits) == 3
    assert splits[0]["amount"] == Decimal("33.34")  # Resto no primeiro (ADR 0001)
    assert splits[1]["amount"] == Decimal("33.33")
    assert splits[2]["amount"] == Decimal("33.33")
    assert sum(s["amount"] for s in splits) == total.amount

def test_calculate_splits_percentage():
    total = Money("100.00")
    # Gabriel 60%, João 40%
    input_data = [
        {"user_id": 1, "value": Decimal("60.0")},
        {"user_id": 2, "value": Decimal("40.0")}
    ]
    
    splits = SplitService.calculate_splits(
        total_amount=total,
        method=SplitMethod.percentage,
        input_data=input_data
    )
    
    assert splits[0]["amount"] == Decimal("60.00")
    assert splits[1]["amount"] == Decimal("40.00")

def test_calculate_splits_fixed():
    total = Money("100.00")
    # Gabriel fixo 70.50, Resto automático para João
    input_data = [
        {"user_id": 1, "value": Decimal("70.50")},
        {"user_id": 2, "value": Decimal("29.50")}
    ]
    
    splits = SplitService.calculate_splits(
        total_amount=total,
        method=SplitMethod.fixed,
        input_data=input_data
    )
    
    assert splits[0]["amount"] == Decimal("70.50")
    assert splits[1]["amount"] == Decimal("29.50")

def test_calculate_splits_invalid_total_fails():
    total = Money("100.00")
    # Soma 110.00
    input_data = [
        {"user_id": 1, "value": Decimal("60.00")},
        {"user_id": 2, "value": Decimal("50.00")}
    ]
    
    with pytest.raises(ValueError, match="A soma da divisão"):
        SplitService.calculate_splits(
            total_amount=total,
            method=SplitMethod.fixed,
            input_data=input_data
        )

def test_calculate_splits_missing_user_ids_equal():
    total = Money("100.00")
    with pytest.raises(ValueError, match="Divisão igual exige a lista de participantes"):
        SplitService.calculate_splits(total, SplitMethod.equal)

def test_calculate_splits_missing_input_data_percentage():
    total = Money("100.00")
    with pytest.raises(ValueError, match="Divisão por porcentagem exige"):
        SplitService.calculate_splits(total, SplitMethod.percentage)

def test_calculate_splits_missing_input_data_fixed():
    total = Money("100.00")
    with pytest.raises(ValueError, match="Divisão por valor fixo exige"):
        SplitService.calculate_splits(total, SplitMethod.fixed)
