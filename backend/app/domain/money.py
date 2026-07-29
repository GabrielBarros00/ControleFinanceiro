from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP, InvalidOperation
from enum import Enum
from typing import List, Union

class Currency(str, Enum):
    """Atalhos para as moedas mais usadas nos testes e no domínio.

    NÃO é a lista de moedas suportadas: o app aceita ~30 (ver
    `frontend/src/lib/currencies.ts`) e `Money` aceita o CÓDIGO como string.
    Como `Currency` herda de `str`, `Money(x, "GBP") == Money(x, "GBP")` e a
    comparação com um membro do enum continua funcionando.
    """
    BRL = "BRL"
    USD = "USD"
    EUR = "EUR"


# Código ISO da moeda: membro do enum acima OU a string crua (ex.: "GBP").
CurrencyCode = Union[Currency, str]

class MoneyError(Exception):
    pass

class Money:
    def __init__(
        self,
        amount: Union[Decimal, str, int],
        currency: CurrencyCode = Currency.BRL,
        allow_negative: bool = False
    ):
        if isinstance(amount, float):
            raise MoneyError("Float input is not allowed. Use Decimal, str, or int.")
        
        try:
            decimal_amount = Decimal(str(amount))
        except InvalidOperation:
            raise MoneyError(f"Invalid amount format: {amount}")
        
        if not allow_negative and decimal_amount < 0:
            raise MoneyError("Negative amounts are not allowed unless explicitly permitted.")
            
        self.currency = currency
        # Arredonda sempre para 2 casas decimais usando ROUND_HALF_UP (arredondamento financeiro comum)
        self.amount = decimal_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def __add__(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise MoneyError(f"Cannot operate on different currencies: {self.currency} and {other.currency}")
        return Money(self.amount + other.amount, self.currency, allow_negative=True)

    def __sub__(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise MoneyError(f"Cannot operate on different currencies: {self.currency} and {other.currency}")
        return Money(self.amount - other.amount, self.currency, allow_negative=True)

    def _total_cents(self) -> int:
        return int((self.amount * 100).to_integral_value())

    def _from_cents(self, cents: int) -> "Money":
        return Money(Decimal(cents) / Decimal(100), self.currency, allow_negative=True)

    def split_equal(self, parts: int) -> List["Money"]:
        """Divisão em centavos inteiros: cota base via divmod e o resto
        distribuído 1 centavo por vez aos PRIMEIROS participantes (ADR 0001).
        Garante soma exata e nenhuma parcela negativa para total >= 0."""
        if parts <= 0:
            raise MoneyError("Parts must be greater than zero.")

        base, remainder = divmod(self._total_cents(), parts)
        return [
            self._from_cents(base + (1 if i < remainder else 0))
            for i in range(parts)
        ]

    def split_by_percentages(self, percentages: List[Decimal]) -> List["Money"]:
        """Cota de cada percentual truncada em centavos; o resto (sempre
        0..N-1 centavos para total >= 0) vai 1 centavo por vez aos PRIMEIROS
        participantes (ADR 0001). Soma exata por construção."""
        if sum(percentages) != Decimal("100"):
            raise MoneyError("Os percentuais devem somar 100.")

        total_cents = self._total_cents()
        floors = [
            int((Decimal(total_cents) * p / Decimal(100)).to_integral_value(rounding=ROUND_FLOOR))
            for p in percentages
        ]
        # floor garante 0 <= resto < N (cada cota fica a menos de 1 centavo da exata)
        remainder = total_cents - sum(floors)
        return [
            self._from_cents(cents + (1 if i < remainder else 0))
            for i, cents in enumerate(floors)
        ]

    def convert(self, target_currency: CurrencyCode, rate: Decimal) -> "Money":
        """
        Converts the current amount to a target currency using a provided rate.
        rate: The multiplier to get from current currency to target currency.
        """
        new_amount = (self.amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return Money(new_amount, target_currency, allow_negative=True)

    def __repr__(self):
        return f"Money({self.amount}, {self.currency})"

    def __eq__(self, other):
        if not isinstance(other, Money):
            return False
        return self.amount == other.amount and self.currency == other.currency

    def __hash__(self):
        # Definir __eq__ sem __hash__ torna a classe UNHASHABLE em Python:
        # Money não podia entrar em set nem ser chave de dict.
        return hash((self.amount, self.currency))
