import httpx
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Optional
import structlog
from app.domain.money import Currency

logger = structlog.get_logger()


class ExchangeRateUnavailable(Exception):
    """Taxa de câmbio indisponível na fonte oficial (BCB PTAX)."""
    def __init__(self, currency, target_date):
        self.currency = currency
        self.target_date = target_date
        super().__init__(
            f"Taxa de câmbio para {currency} indisponível próximo a {target_date}"
        )


class CurrencyService:
    """
    Service to handle currency conversion using official rates from the 
    Brazilian Central Bank (BCB) Olinda API.
    """
    
    # Official BCB Olinda PTAX API
    BASE_URL = "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata"
    
    # Cache to store rates retrieved during the same request/lifecycle
    _cache: Dict[str, Decimal] = {}

    @classmethod
    async def get_rate(
        cls, 
        from_currency: Currency, 
        to_currency: Currency = Currency.BRL, 
        target_date: Optional[date] = None
    ) -> Decimal:
        """
        Retrieves the exchange rate between two currencies.
        Default target is BRL.
        """
        if from_currency == to_currency:
            return Decimal("1.0")
            
        if target_date is None:
            target_date = date.today()
            
        # PTAX rates are usually not available on weekends or early morning.
        # We might need to look back for the latest available rate.
        search_date = target_date
        
        # Simple cache key
        cache_key = f"{from_currency}_{to_currency}_{search_date.isoformat()}"
        if cache_key in cls._cache:
            return cls._cache[cache_key]

        # Currently we only support BRL as base or target
        if to_currency != Currency.BRL and from_currency != Currency.BRL:
            # Indirect conversion via BRL
            rate_from_to_brl = await cls.get_rate(from_currency, Currency.BRL, search_date)
            rate_brl_to_to = Decimal("1.0") / await cls.get_rate(to_currency, Currency.BRL, search_date)
            return (rate_from_to_brl * rate_brl_to_to).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

        # Logic for BRL target
        # API requires MM-DD-YYYY
        date_str = search_date.strftime("%m-%d-%Y")
        
        # BCB API expects USD/EUR to BRL rate
        # CotacaoMoedaDia(moeda=@moeda,dataCotacao=@dataCotacao)
        url = f"{cls.BASE_URL}/CotacaoMoedaDia(moeda=@moeda,dataCotacao=@dataCotacao)"
        params = {
            "@moeda": f"'{from_currency.value}'",
            "@dataCotacao": f"'{date_str}'",
            "$format": "json",
            "$select": "cotacaoVenda"
        }

        try:
            async with httpx.AsyncClient() as client:
                # We try up to 5 days back for weekend/holiday coverage
                for _ in range(5):
                    response = await client.get(url, params=params, timeout=10.0)
                    response.raise_for_status()
                    data = response.json()
                    
                    if data.get("value") and len(data["value"]) > 0:
                        rate = Decimal(str(data["value"][0]["cotacaoVenda"]))
                        cls._cache[cache_key] = rate
                        return rate
                    
                    # Look back one day
                    search_date -= timedelta(days=1)
                    date_str = search_date.strftime("%m-%d-%Y")
                    params["@dataCotacao"] = f"'{date_str}'"
                    
            # Sem taxa nos últimos 5 dias: erro tipado (o caller responde 422, nunca 500)
            raise ExchangeRateUnavailable(from_currency, target_date)

        except ExchangeRateUnavailable:
            raise
        except Exception as e:
            logger.error("currency_api_error", error=str(e), currency=from_currency, date=target_date)
            raise ExchangeRateUnavailable(from_currency, target_date) from e
