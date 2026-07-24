"""CurrencyService (sync) — parsing das fontes PTAX (oficial) e mercado
(fawazahmed0), look-back, cache. httpx mockado (sem rede)."""
from datetime import date
from decimal import Decimal

import pytest

from app.services import currency_service as cs
from app.services.currency_service import CurrencyService, ExchangeRateUnavailable


class _Resp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception("http error")

    def json(self):
        return self._data


class _Client:
    """httpx.Client fake: devolve as respostas em ordem (repete a última)."""
    def __init__(self, responses):
        self._responses = list(responses)
        self._i = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, **kwargs):
        r = self._responses[min(self._i, len(self._responses) - 1)]
        self._i += 1
        return r


def _patch(monkeypatch, responses):
    monkeypatch.setattr(cs.httpx, "Client", lambda *a, **k: _Client(responses))


@pytest.fixture(autouse=True)
def _clear_cache():
    CurrencyService._cache_sync.clear()
    yield
    CurrencyService._cache_sync.clear()


def test_same_currency_is_base():
    assert CurrencyService.get_rate_sync("BRL", "BRL", date(2026, 5, 4)) == (Decimal("1.0"), "base")


def test_ptax_parses_cotacao_venda(monkeypatch):
    _patch(monkeypatch, [_Resp({"value": [{"cotacaoVenda": 5.50}]})])
    assert CurrencyService.get_rate_sync("USD", "BRL", date(2026, 5, 4)) == (Decimal("5.5"), "ptax")


def test_ptax_look_back_ate_achar(monkeypatch):
    # fim de semana: 1º dia vazio, 2º dia com cotação
    _patch(monkeypatch, [_Resp({"value": []}), _Resp({"value": [{"cotacaoVenda": 5.40}]})])
    assert CurrencyService.get_rate_sync("USD", "BRL", date(2026, 5, 4)) == (Decimal("5.4"), "ptax")


def test_ptax_indisponivel_apos_look_back(monkeypatch):
    _patch(monkeypatch, [_Resp({"value": []})])
    with pytest.raises(ExchangeRateUnavailable):
        CurrencyService.get_rate_sync("USD", "BRL", date(2026, 5, 4))


def test_mercado_parses_fawazahmed(monkeypatch):
    # ARS não é PTAX → fonte de mercado (formato fawazahmed0)
    _patch(monkeypatch, [_Resp({"date": "2026-05-04", "ars": {"brl": 0.0055}})])
    assert CurrencyService.get_rate_sync("ARS", "BRL", date(2026, 5, 4)) == (Decimal("0.0055"), "market")


def test_cache_hit(monkeypatch):
    CurrencyService._cache_sync["USD_BRL_2088-01-01"] = (Decimal("7.77"), "ptax")
    # sem mock de httpx: se bater na rede, o teste falharia — prova que veio do cache
    assert CurrencyService.get_rate_sync("USD", "BRL", date(2088, 1, 1)) == (Decimal("7.77"), "ptax")
