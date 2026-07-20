import pytest
from decimal import Decimal
from datetime import date
from app.services.currency_service import CurrencyService, ExchangeRateUnavailable
from app.domain.money import Currency
from unittest.mock import patch, MagicMock

@pytest.mark.asyncio
async def test_get_rate_brl_to_brl():
    rate = await CurrencyService.get_rate(Currency.BRL, Currency.BRL)
    assert rate == Decimal("1.0")

@pytest.mark.asyncio
async def test_get_rate_usd_to_brl_success():
    # Clear cache for deterministic test
    CurrencyService._cache = {}
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "value": [{"cotacaoVenda": 5.50}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        rate = await CurrencyService.get_rate(Currency.USD, Currency.BRL, target_date=date(2026, 5, 4))
        assert rate == Decimal("5.5")

@pytest.mark.asyncio
async def test_get_rate_retry_logic():
    CurrencyService._cache = {}
    
    # First call returns empty (e.g. weekend), second call returns rate
    mock_response_empty = MagicMock()
    mock_response_empty.status_code = 200
    mock_response_empty.json.return_value = {"value": []}
    mock_response_empty.raise_for_status = MagicMock()
    
    mock_response_success = MagicMock()
    mock_response_success.status_code = 200
    mock_response_success.json.return_value = {"value": [{"cotacaoVenda": 5.40}]}
    mock_response_success.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.get", side_effect=[mock_response_empty, mock_response_success]):
        # Will retry once
        rate = await CurrencyService.get_rate(Currency.USD, Currency.BRL, target_date=date(2026, 5, 4))
        assert rate == Decimal("5.4")

@pytest.mark.asyncio
async def test_get_rate_usd_to_eur_indirect():
    CurrencyService._cache = {}
    
    # USD -> BRL = 5.0
    mock_resp_usd = MagicMock()
    mock_resp_usd.json.return_value = {"value": [{"cotacaoVenda": 5.0}]}
    mock_resp_usd.status_code = 200
    
    # EUR -> BRL = 6.0
    mock_resp_eur = MagicMock()
    mock_resp_eur.json.return_value = {"value": [{"cotacaoVenda": 6.0}]}
    mock_resp_eur.status_code = 200

    with patch("httpx.AsyncClient.get", side_effect=[mock_resp_usd, mock_resp_eur]):
        rate = await CurrencyService.get_rate(Currency.USD, Currency.EUR, target_date=date(2026, 5, 4))
        # 5.0 / 6.0 = 0.83333... -> 0.8333
        assert rate == Decimal("0.8333")

@pytest.mark.asyncio
async def test_get_rate_not_found_after_retries():
    CurrencyService._cache = {}
    mock_response_empty = MagicMock()
    mock_response_empty.json.return_value = {"value": []}
    mock_response_empty.status_code = 200
    mock_response_empty.raise_for_status = MagicMock()
    
    with patch("httpx.AsyncClient.get", return_value=mock_response_empty):
        with pytest.raises(ExchangeRateUnavailable):
            await CurrencyService.get_rate(Currency.USD, Currency.BRL, target_date=date(2026, 5, 4))

@pytest.mark.asyncio
async def test_get_rate_cache_hit():
    # Deterministic test for cache hit
    test_date = date(2088, 1, 1)
    key = f"{Currency.USD}_{Currency.BRL}_{test_date.isoformat()}"
    CurrencyService._cache[key] = Decimal("7.77")
    
    rate = await CurrencyService.get_rate(Currency.USD, Currency.BRL, target_date=test_date)
    assert rate == Decimal("7.77")

@pytest.mark.asyncio
async def test_get_rate_default_today():
    mock_today = date(2077, 7, 7)
    with patch("app.services.currency_service.date") as mock_date:
        mock_date.today.return_value = mock_today
        key = f"{Currency.USD}_{Currency.BRL}_{mock_today.isoformat()}"
        if key in CurrencyService._cache:
            del CurrencyService._cache[key]
            
        mock_response = MagicMock()
        mock_response.json.return_value = {"value": [{"cotacaoVenda": 5.88}]}
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        
        with patch("httpx.AsyncClient.get", return_value=mock_response):
            rate = await CurrencyService.get_rate(Currency.USD, Currency.BRL)
            assert rate == Decimal("5.88")
