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
    def get_or_fetch(
        cls,
        db: Session,
        currency: str,
        target_date: date,
        *,
        allow_fetch: bool = True,
    ) -> Tuple[Decimal, str]:
        """Taxa moeda→BRL do dia. Com `allow_fetch=False` NUNCA vai à rede.

        O modo offline existe para o caminho de LEITURA (materialização
        preguiçosa nas rotas GET): buscar cotação ali podia bloquear um
        `GET /transactions/` por até ~50s esperando uma fonte externa. Sem taxa
        no store, o chamador do modo offline desiste da ocorrência — o backfill
        agendado ou a próxima mutação preenchem a lacuna.
        """
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

        if allow_fetch:
            try:
                rate, source = CurrencyService.get_rate_sync(currency, "BRL", target_date)
            except ExchangeRateUnavailable:
                return cls._fallback_or_raise(db, currency, target_date)
            cls._save(db, currency, target_date, rate, source)
            return rate, source

        return cls._fallback_or_raise(db, currency, target_date)

    @classmethod
    def rate_between(
        cls,
        db: Session,
        from_currency: str,
        to_currency: str,
        target_date: date,
        *,
        allow_fetch: bool = True,
    ) -> Tuple[Decimal, str]:
        """Taxa `from → to` na data. **Use esta, não `get_or_fetch`, para converter
        para a moeda-base de um workspace.**

        O store guarda apenas X→BRL, então a taxa entre duas moedas quaisquer é a
        cruzada `(from→BRL) / (to→BRL)`. Usar `get_or_fetch(from)` direto só está
        certo quando a base É BRL — e a moeda-base é configurável por workspace
        desde a Onda 5. Num workspace em USD, `get_or_fetch("EUR")` devolvia a
        taxa EUR→BRL (~6,3) e o lançamento de EUR 50 era gravado como 315 USD;
        pior, `get_or_fetch("BRL")` devolve 1,0 e uma despesa em BRL virava o
        mesmo número em USD, sem nenhum sinal de erro.

        Levanta `ExchangeRateUnavailable` (com a moeda que faltou) como o
        `get_or_fetch`, para os chamadores manterem o tratamento que já têm.
        """
        from_currency = str(from_currency).upper()
        to_currency = str(to_currency).upper()
        if from_currency == to_currency:
            return Decimal("1.0"), "base"

        from_brl, from_source = cls.get_or_fetch(
            db, from_currency, target_date, allow_fetch=allow_fetch
        )
        to_brl, to_source = cls.get_or_fetch(
            db, to_currency, target_date, allow_fetch=allow_fetch
        )
        # A PTAX é oficial só CONTRA o real: uma taxa cruzada derivada de duas
        # cotações não é a taxa oficial do par, e o selo na UI não pode dizer que é.
        if to_currency == "BRL":
            source = from_source
        elif from_currency == "BRL":
            source = to_source
        else:
            source = "market"
        return from_brl / to_brl, source

    @classmethod
    def _fallback_or_raise(
        cls, db: Session, currency: str, target_date: date
    ) -> Tuple[Decimal, str]:
        """Taxa mais recente ANTERIOR dentro da janela de tolerância (resiliência)."""
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
        raise ExchangeRateUnavailable(currency, target_date)

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
