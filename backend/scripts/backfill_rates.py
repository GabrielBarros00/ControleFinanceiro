"""Backfill do store de câmbio (tabela `exchangerate`).

Coleta as taxas moeda→BRL dos últimos N dias (padrão 7), pulando o que já existe
e o que a fonte não tem (fim de semana/feriado no PTAX, data fora do histórico da
fonte). Vai até o dia ANTERIOR (D-1), porque a cotação do dia corrente pode ainda
não ter fechado.

Uso (da raiz do backend, com o .env carregado):
    python scripts/backfill_rates.py [dias]

Rode diariamente via cron para coletar o dia anterior e preencher lacunas:
    0 6 * * *  cd /app/backend && python scripts/backfill_rates.py 7
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session  # noqa: E402
from app.db.engine import engine  # noqa: E402
from app.services.currency_service import CurrencyService  # noqa: E402
from app.services.exchange_rate_store import ExchangeRateStore  # noqa: E402

# Por padrão coleta as moedas OFICIAIS do PTAX (histórico confiável). As de
# mercado (ARS, CLP, ...) populam sozinhas na 1ª conversão que as usa.
DEFAULT_CURRENCIES = sorted(CurrencyService.PTAX_CURRENCIES)


def main() -> None:
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    end = date.today() - timedelta(days=1)              # D-1
    start = end - timedelta(days=max(days - 1, 0))
    with Session(engine) as db:
        result = ExchangeRateStore.backfill(db, DEFAULT_CURRENCIES, start, end)
    print(f"backfill {start}..{end} {DEFAULT_CURRENCIES}: {result}")


if __name__ == "__main__":
    main()
