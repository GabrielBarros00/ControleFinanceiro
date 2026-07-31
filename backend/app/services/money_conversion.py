"""Conversão para a moeda de relatório da PESSOA, com o direito de dizer "não sei".

Extraído de `OverviewService._converte` quando o caixa efetivo (ADR 0022) passou a
precisar da mesma regra: `overview_service` importa `cashflow_service`, então a
função não podia continuar morando no primeiro.

O ponto do módulo é o retorno `None`. Toda soma que atravessa moedas tem três
resultados possíveis — o valor, zero, e *não dá para saber* — e o terceiro é o que
os sistemas costumam perder no caminho, porque `0` é um número e cabe em qualquer
lugar. Foi exatamente o que aconteceu: um `_converte(...) or ZERO` transformava
"sem cotação" em "não deve nada", e uma dívida de USD 100 sumia da tela sem aviso.

Quem chama tem de decidir o que fazer com o `None` — e a decisão certa, no ADR 0006,
é deixar o valor de fora E contá-lo, para a tela poder dizer que omitiu algo.
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlmodel import Session

from app.services.currency_service import ExchangeRateUnavailable
from app.services.exchange_rate_store import ExchangeRateStore

ZERO = Decimal("0.00")


def converte(
    db: Session, valor: Decimal, de: str, para: str, quando: date
) -> Optional[Decimal]:
    """`valor` de `de` para `para` na data `quando`; `None` quando não há taxa.

    Sem `allow_fetch`: leitura de relatório não sai para a internet (ADR 0015). O
    store é preenchido pelo backfill e pela escrita.
    """
    if valor == ZERO or de == para:
        return valor
    try:
        taxa, _fonte = ExchangeRateStore.rate_between(db, de, para, quando, allow_fetch=False)
    except ExchangeRateUnavailable:
        return None
    return (valor * taxa).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
