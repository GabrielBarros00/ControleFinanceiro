import pytest
from decimal import Decimal
from app.domain.money import Money, Currency, MoneyError

def test_money_creation_from_string():
    m = Money("100.50")
    assert m.amount == Decimal("100.50")
    assert m.currency == Currency.BRL

def test_money_creation_from_int():
    m = Money(100)
    assert m.amount == Decimal("100.00")

def test_money_creation_from_decimal():
    m = Money(Decimal("10.25"))
    assert m.amount == Decimal("10.25")

def test_money_rejects_float():
    with pytest.raises(MoneyError, match="Float input is not allowed"):
        Money(100.50)

def test_money_quantization():
    # Deve arredondar para 2 casas decimais (BRL padrão)
    m = Money("100.555")
    assert m.amount == Decimal("100.56")

def test_money_arithmetic_addition():
    m1 = Money("10.50")
    m2 = Money("20.25")
    result = m1 + m2
    assert result.amount == Decimal("30.75")

def test_money_different_currency_fails():
    m1 = Money("10.00", Currency.BRL)
    m2 = Money("10.00", Currency.USD)
    with pytest.raises(MoneyError, match="Cannot operate on different currencies"):
        m1 + m2

def test_money_split_equal():
    total = Money("100.00")
    # 100 / 3 = 33.34 + 33.33 + 33.33 (resto vai aos primeiros — ADR 0001)
    splits = total.split_equal(3)

    assert len(splits) == 3
    assert splits[0].amount == Decimal("33.34")  # O primeiro recebe o resto
    assert splits[1].amount == Decimal("33.33")
    assert splits[2].amount == Decimal("33.33")
    assert sum(s.amount for s in splits) == total.amount

def test_money_split_percentage():
    total = Money("100.00")
    # 60% e 40%
    splits = total.split_by_percentages([Decimal("60.0"), Decimal("40.0")])
    assert splits[0].amount == Decimal("60.00")
    assert splits[1].amount == Decimal("40.00")

def test_money_split_percentage_rounding():
    total = Money("100.00")
    # 33.33%, 33.33%, 33.34% -> Deve somar 100%
    # No caso de porcentagens que não somam 100, deve falhar
    with pytest.raises(MoneyError, match="Os percentuais devem somar 100"):
        total.split_by_percentages([Decimal("33.3"), Decimal("33.3")])

def test_money_negative_not_allowed_by_default():
    with pytest.raises(MoneyError, match="Negative amounts are not allowed"):
        Money("-10.00")

def test_money_negative_allowed_explicitly():
    m = Money("-10.00", allow_negative=True)
    assert m.amount == Decimal("-10.00")

def test_money_invalid_format():
    with pytest.raises(MoneyError, match="Invalid amount format"):
        Money("abc")

def test_money_subtraction():
    m1 = Money("100.00")
    m2 = Money("40.00")
    result = m1 - m2
    assert result.amount == Decimal("60.00")

def test_money_subtraction_different_currency_fails():
    m1 = Money("10.00", Currency.BRL)
    m2 = Money("10.00", Currency.USD)
    with pytest.raises(MoneyError, match="Cannot operate on different currencies"):
        m1 - m2

def test_money_split_equal_invalid_parts():
    m = Money("100.00")
    with pytest.raises(MoneyError, match="Parts must be greater than zero"):
        m.split_equal(0)
    with pytest.raises(MoneyError, match="Parts must be greater than zero"):
        m.split_equal(-1)

def test_money_convert():
    m = Money("100.00", Currency.BRL)
    # Rate 0.2 means 1 BRL = 0.2 USD
    result = m.convert(Currency.USD, Decimal("0.2"))
    assert result.amount == Decimal("20.00")
    assert result.currency == Currency.USD

def test_money_split_percentage_adjustment():
    total = Money("10.00")
    # 33.33%, 33.33%, 33.34% — pisos em centavos: 333, 333, 333 (soma 999).
    # O centavo restante vai ao PRIMEIRO participante (ADR 0001).
    splits = total.split_by_percentages([Decimal("33.33"), Decimal("33.33"), Decimal("33.34")])
    assert splits[0].amount == Decimal("3.34")
    assert splits[1].amount == Decimal("3.33")
    assert splits[2].amount == Decimal("3.33")
    assert sum(s.amount for s in splits) == total.amount

def test_money_repr():
    m = Money("100.50", Currency.BRL)
    assert repr(m) == "Money(100.50, Currency.BRL)"

def test_money_equality():
    m1 = Money("100.00", Currency.BRL)
    m2 = Money("100.00", Currency.BRL)
    m3 = Money("100.00", Currency.USD)
    m4 = Money("101.00", Currency.BRL)
    
    assert m1 == m2
    assert m1 != m3
    assert m1 != m4
    assert m1 != "100.00" # Testing non-Money object
