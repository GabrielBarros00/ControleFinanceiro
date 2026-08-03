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
from typing import Dict, Optional, Tuple

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


class ConversorPorData:
    """`converte` com a taxa memoizada por (moeda, dia), para um destino fixo.

    O caixa converte cada movimento pela DATA EFETIVA dele (ADR 0022), e não mais
    pelo dia 1º do mês. Chamar `converte` por linha significaria uma consulta ao
    store por linha; os pares (moeda, dia) distintos de um mês são poucos — no
    máximo 31 por moeda —, então memoizar transforma N consultas em uma por par.

    Mantém o contrato do `None`: taxa ausente devolve `None`, e quem chama decide
    (a política do ADR 0006 é omitir E contar, nunca virar zero).
    """

    __slots__ = ("_db", "_destino", "_cache")

    def __init__(self, db: Session, destino: str) -> None:
        self._db = db
        self._destino = destino
        self._cache: Dict[Tuple[str, date], Optional[Decimal]] = {}

    @property
    def destino(self) -> str:
        return self._destino

    def __call__(self, valor: Decimal, de: str, quando: date) -> Optional[Decimal]:
        if valor == ZERO or de == self._destino:
            return valor
        chave = (de, quando)
        if chave not in self._cache:
            try:
                taxa, _fonte = ExchangeRateStore.rate_between(
                    self._db, de, self._destino, quando, allow_fetch=False
                )
            except ExchangeRateUnavailable:
                taxa = None
            self._cache[chave] = taxa
        taxa = self._cache[chave]
        if taxa is None:
            return None
        return (valor * taxa).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
