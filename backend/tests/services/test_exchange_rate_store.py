"""ExchangeRateStore: hit no store, miss+grava, fallback quando a fonte cai,
backfill idempotente."""
from datetime import date
from decimal import Decimal

from sqlmodel import Session, select

from app.models.exchange_rate import ExchangeRate
from app.services import currency_service as cs
from app.services.currency_service import ExchangeRateUnavailable
from app.services.exchange_rate_store import ExchangeRateStore


def test_hit_no_store(db_session: Session):
    db_session.add(ExchangeRate(currency="USD", rate_date=date(2026, 5, 4), rate=Decimal("5.10"), source="ptax"))
    db_session.commit()
    # sem mock: se batesse na rede, falharia — prova que veio do store
    assert ExchangeRateStore.get_or_fetch(db_session, "USD", date(2026, 5, 4)) == (Decimal("5.10"), "ptax")


def test_miss_busca_e_grava(db_session: Session, monkeypatch):
    monkeypatch.setattr(cs.CurrencyService, "get_rate_sync", lambda *a, **k: (Decimal("5.25"), "ptax"))
    assert ExchangeRateStore.get_or_fetch(db_session, "USD", date(2026, 5, 5)) == (Decimal("5.25"), "ptax")
    stored = db_session.exec(
        select(ExchangeRate).where(ExchangeRate.currency == "USD", ExchangeRate.rate_date == date(2026, 5, 5))
    ).first()
    assert stored is not None and stored.rate == Decimal("5.25")


def test_fallback_quando_fonte_cai(db_session: Session, monkeypatch):
    db_session.add(ExchangeRate(currency="USD", rate_date=date(2026, 5, 6), rate=Decimal("5.30"), source="ptax"))
    db_session.commit()

    def boom(*a, **k):
        raise ExchangeRateUnavailable("USD", date(2026, 5, 7))

    monkeypatch.setattr(cs.CurrencyService, "get_rate_sync", boom)
    rate, source = ExchangeRateStore.get_or_fetch(db_session, "USD", date(2026, 5, 7))
    assert rate == Decimal("5.30")  # cai na mais recente anterior


def test_backfill_idempotente(db_session: Session, monkeypatch):
    monkeypatch.setattr(cs.CurrencyService, "get_rate_sync", lambda cur, to, d: (Decimal("5.00"), "ptax"))
    r1 = ExchangeRateStore.backfill(db_session, ["USD", "EUR"], date(2026, 5, 1), date(2026, 5, 3))
    assert r1["fetched"] == 6 and r1["missing"] == 0  # 2 moedas × 3 dias
    r2 = ExchangeRateStore.backfill(db_session, ["USD", "EUR"], date(2026, 5, 1), date(2026, 5, 3))
    assert r2["skipped"] == 6 and r2["fetched"] == 0
