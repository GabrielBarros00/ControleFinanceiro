from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable, Tuple

from sqlmodel import Session, select

from app.models.exchange_rate import ExchangeRate
from app.services.currency_service import CurrencyService, ExchangeRateUnavailable


class ExchangeRateStore:
    """Store local (tabela `exchangerate`) de taxas moeda→BRL por dia.

    `get_or_fetch` é a porta de entrada da conversão: usa a taxa gravada; se não
    houver, busca na fonte (PTAX/mercado), grava e devolve; se a fonte cair, cai
    na taxa mais recente ANTERIOR no store (resiliência). Não comita nas leituras
    lazy (o request já comita) — só o backfill comita."""

    _FALLBACK_LOOKBACK_DAYS = 15

    @classmethod
    def get_or_fetch(cls, db: Session, currency: str, target_date: date) -> Tuple[Decimal, str]:
        currency = str(currency).upper()
        if currency == "BRL":
            return Decimal("1.0"), "base"

        row = db.exec(
            select(ExchangeRate).where(
                ExchangeRate.currency == currency,
                ExchangeRate.rate_date == target_date,
            )
        ).first()
        if row:
            return row.rate, row.source

        try:
            rate, source = CurrencyService.get_rate_sync(currency, "BRL", target_date)
        except ExchangeRateUnavailable:
            fallback = db.exec(
                select(ExchangeRate)
                .where(
                    ExchangeRate.currency == currency,
                    ExchangeRate.rate_date <= target_date,
                    ExchangeRate.rate_date >= target_date - timedelta(days=cls._FALLBACK_LOOKBACK_DAYS),
                )
                .order_by(ExchangeRate.rate_date.desc())
            ).first()
            if fallback:
                return fallback.rate, fallback.source
            raise

        cls._save(db, currency, target_date, rate, source)
        return rate, source

    @staticmethod
    def _save(db: Session, currency: str, rate_date: date, rate: Decimal, source: str) -> ExchangeRate:
        """Grava a taxa (idempotente pela unique currency+date). Não comita."""
        existing = db.exec(
            select(ExchangeRate).where(
                ExchangeRate.currency == currency,
                ExchangeRate.rate_date == rate_date,
            )
        ).first()
        if existing:
            return existing
        row = ExchangeRate(currency=currency, rate_date=rate_date, rate=rate, source=source)
        db.add(row)
        db.flush()
        return row

    @classmethod
    def backfill(
        cls,
        db: Session,
        currencies: Iterable[str],
        start_date: date,
        end_date: date,
    ) -> dict:
        """Preenche o store para as moedas no intervalo [start, end], pulando o
        que já existe e contando como 'missing' o que a fonte não tem (fim de
        semana/feriado no PTAX, data fora do histórico da fonte). Comita no fim."""
        fetched = skipped = missing = 0
        codes = [c.upper() for c in currencies if c.upper() != "BRL"]
        d = start_date
        while d <= end_date:
            for cur in codes:
                exists = db.exec(
                    select(ExchangeRate).where(
                        ExchangeRate.currency == cur,
                        ExchangeRate.rate_date == d,
                    )
                ).first()
                if exists:
                    skipped += 1
                    continue
                try:
                    rate, source = CurrencyService.get_rate_sync(cur, "BRL", d)
                    cls._save(db, cur, d, rate, source)
                    fetched += 1
                except ExchangeRateUnavailable:
                    missing += 1
            d += timedelta(days=1)
        db.commit()
        return {"fetched": fetched, "skipped": skipped, "missing": missing}
