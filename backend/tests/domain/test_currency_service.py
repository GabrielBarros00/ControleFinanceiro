"""Roteamento do CurrencyService: PTAX (oficial) para as majores → BRL, senão
fonte de mercado. Fetchers mockados (sem rede)."""
from datetime import date
from decimal import Decimal

from app.services.currency_service import CurrencyService


def test_get_rate_sync_route_ptax_vs_market(monkeypatch):
    CurrencyService._cache_sync.clear()
    monkeypatch.setattr(CurrencyService, "_fetch_ptax_sync",
                        classmethod(lambda cls, code, d: Decimal("5.00")))
    monkeypatch.setattr(CurrencyService, "_fetch_market_sync",
                        classmethod(lambda cls, f, t, d: Decimal("0.005")))

    # USD é PTAX (oficial)
    assert CurrencyService.get_rate_sync("USD", "BRL", date(2026, 3, 10)) == (Decimal("5.00"), "ptax")
    # ARS não é PTAX → mercado (referência)
    assert CurrencyService.get_rate_sync("ARS", "BRL", date(2026, 3, 10)) == (Decimal("0.005"), "market")
    # mesma moeda
    assert CurrencyService.get_rate_sync("BRL", "BRL", date(2026, 3, 10)) == (Decimal("1.0"), "base")
