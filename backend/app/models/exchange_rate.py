from datetime import date, datetime, UTC
from decimal import Decimal
from typing import Optional
from sqlmodel import SQLModel, Field, UniqueConstraint


class ExchangeRate(SQLModel, table=True):
    """Store local de taxas de câmbio para BRL, por moeda e dia. Preenchido
    preguiçosamente (na 1ª conversão que precisa) e por um backfill diário. Dá
    velocidade (evita bater na API repetido), resiliência (funciona se a fonte
    cair) e histórico (taxa da data real do lançamento)."""
    __table_args__ = (
        UniqueConstraint("currency", "rate_date", name="uq_exchange_rate_currency_date"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    currency: str = Field(index=True)      # moeda de origem (destino sempre BRL)
    rate_date: date = Field(index=True)    # data da cotação
    rate: Decimal = Field(decimal_places=6, max_digits=20)
    source: str                            # 'ptax' (oficial) | 'market' (referência)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
