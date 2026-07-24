import httpx
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, Optional
import structlog

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

    # Moedas cotadas oficialmente pelo PTAX (CotacaoMoedaDia). Fora dessas, cai
    # numa fonte de MERCADO (referência, não oficial).
    PTAX_CURRENCIES = {"AUD", "CAD", "CHF", "DKK", "EUR", "GBP", "JPY", "NOK", "SEK", "USD"}
    _cache_sync: Dict[str, tuple] = {}

    @classmethod
    def get_rate_sync(
        cls,
        from_code,
        to_code: str = "BRL",
        target_date: Optional[date] = None,
    ) -> tuple:
        """SÍNCRONA (fluxo de criação/edição). Devolve **(taxa, fonte)**: fonte é
        `'ptax'` (oficial, majores→BRL, bate com o cartão), `'market'`
        (referência fawazahmed0, 200+ moedas) ou `'base'` (mesma moeda)."""
        from_code = str(from_code).upper()
        to_code = str(to_code).upper()
        if from_code == to_code:
            return Decimal("1.0"), "base"
        if target_date is None:
            target_date = date.today()

        cache_key = f"{from_code}_{to_code}_{target_date.isoformat()}"
        if cache_key in cls._cache_sync:
            return cls._cache_sync[cache_key]

        if to_code == "BRL" and from_code in cls.PTAX_CURRENCIES:
            result = (cls._fetch_ptax_sync(from_code, target_date), "ptax")
        else:
            result = (cls._fetch_market_sync(from_code, to_code, target_date), "market")
        cls._cache_sync[cache_key] = result
        return result

    @classmethod
    def _fetch_ptax_sync(cls, from_code: str, target_date: date) -> Decimal:
        """PTAX oficial (BCB) para as majores → BRL, com look-back de 5 dias
        (fins de semana/feriados). `cotacaoVenda` = taxa usada em compras."""
        search_date = target_date
        url = f"{cls.BASE_URL}/CotacaoMoedaDia(moeda=@moeda,dataCotacao=@dataCotacao)"
        params = {
            "@moeda": f"'{from_code}'",
            "@dataCotacao": f"'{search_date.strftime('%m-%d-%Y')}'",
            "$format": "json",
            "$select": "cotacaoVenda",
        }
        try:
            with httpx.Client() as client:
                for _ in range(5):
                    response = client.get(url, params=params, timeout=10.0)
                    response.raise_for_status()
                    data = response.json()
                    if data.get("value"):
                        return Decimal(str(data["value"][0]["cotacaoVenda"]))
                    search_date -= timedelta(days=1)
                    params["@dataCotacao"] = f"'{search_date.strftime('%m-%d-%Y')}'"
            raise ExchangeRateUnavailable(from_code, target_date)
        except ExchangeRateUnavailable:
            raise
        except Exception as e:
            logger.error("currency_api_error", error=str(e), currency=from_code, date=target_date)
            raise ExchangeRateUnavailable(from_code, target_date) from e

    @classmethod
    def _fetch_market_sync(cls, from_code: str, to_code: str, target_date: date) -> Decimal:
        """Fonte de MERCADO (fawazahmed0/exchange-api): 200+ moedas, histórico,
        sem chave, via CDN. Referência — NÃO é a taxa oficial PTAX. Tenta a data
        pedida e depois a última, em dois hosts."""
        fl, tl = from_code.lower(), to_code.lower()
        # "latest" só faz sentido para hoje/futuro (taxa mais recente). Para datas
        # passadas NÃO cai no "latest" — senão gravaria a taxa de hoje num dia antigo.
        labels = [target_date.isoformat()]
        if target_date >= date.today():
            labels.append("latest")
        candidates = []
        for d in labels:
            candidates.append(f"https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{d}/v1/currencies/{fl}.json")
            candidates.append(f"https://{d}.currency-api.pages.dev/v1/currencies/{fl}.json")
        try:
            with httpx.Client(follow_redirects=True) as client:
                for url in candidates:
                    try:
                        r = client.get(url, timeout=10.0)
                    except Exception:
                        continue
                    if r.status_code != 200:
                        continue
                    rate = (r.json().get(fl) or {}).get(tl)
                    if rate is not None:
                        return Decimal(str(rate))
        except Exception as e:
            logger.error("market_api_error", error=str(e), currency=from_code, date=target_date)
        raise ExchangeRateUnavailable(from_code, target_date)
