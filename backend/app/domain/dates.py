"""Aritmética de datas por MÊS DE CALENDÁRIO (não 30 dias) e o fuso do aplicativo.

Parcelamento, financiamento e recorrência avançam por mês real — somar
`timedelta(days=30)` desloca o vencimento e erra o rótulo de mês.

E aqui mora a referência ÚNICA de "hoje". O backend tinha duas, convivendo:
`datetime.now(UTC)` (fatura vencida, compromissos, carimbos) e `date.today()`
(recorrência, previsão, data de cotação). Num fuso negativo elas discordam todo
dia entre 21h e a meia-noite, e um movimento feito às 22h de 31 de julho em São
Paulo pertencia a julho para uma e a agosto para a outra. O fuso vinha só de
`TZ` nos serviços do Compose — ausente em qualquer processo iniciado à mão.
"""
import calendar
from datetime import UTC, date, datetime, time, tzinfo
from functools import lru_cache
from typing import Optional, TypeVar
from zoneinfo import ZoneInfo

from app.core.config import settings

D = TypeVar("D", date, datetime)


class InvalidMonth(ValueError):
    """Mês fora do formato YYYY-MM (o chamador traduz para 400)."""


@lru_cache(maxsize=8)
def _resolve_tz(nome: str) -> tzinfo:
    """Resolve o nome do fuso uma vez só. `ZoneInfo` lê disco/pacote a cada
    construção, e isto é chamado em laço (uma vez por mês da série)."""
    try:
        return ZoneInfo(nome)
    except Exception:
        # `timezone.utc`, NÃO `ZoneInfo("UTC")`: sem a base de fusos instalada
        # (Windows sem `tzdata`) o fallback levantaria a mesma exceção que
        # deveria absorver, e o processo caía em vez de degradar.
        return UTC


def app_tz() -> tzinfo:
    """O fuso do calendário do aplicativo (`settings.APP_TIMEZONE`).

    Fuso desconhecido cai em UTC em vez de derrubar a aplicação: uma variável de
    ambiente com erro de digitação não deve impedir o backend de subir, e UTC é
    o comportamento que já existia.
    """
    return _resolve_tz(settings.APP_TIMEZONE)


def today_local() -> date:
    """O dia de calendário de HOJE no fuso do aplicativo.

    Substitui tanto `date.today()` (que segue o fuso do PROCESSO — UTC no CI e
    em qualquer uvicorn sem `TZ`) quanto `datetime.now(UTC).date()` (que vira o
    dia seguinte três horas antes em Brasília).
    """
    return datetime.now(app_tz()).date()


def to_local(momento: datetime) -> datetime:
    """O mesmo INSTANTE, lido no fuso do aplicativo.

    `datetime` naive é assumido UTC — é como as colunas guardam (o SQLite não
    tem fuso, e `datetime.now(UTC)` perde o tzinfo ao ser gravado).
    """
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=UTC)
    return momento.astimezone(app_tz())


def month_key_local(momento: datetime) -> str:
    """Mês de calendário LOCAL de um instante → `"YYYY-MM"`.

    É o que `billing_month` sempre quis dizer. Derivar com
    `momento.strftime("%Y-%m")` trata um instante UTC como se fosse uma data de
    calendário: uma despesa lançada às 22h de 31 de julho em São Paulo é gravada
    como `2026-08-01T01:00Z` e virava competência de AGOSTO — invisível em todas
    as telas, que pedem julho. O formulário mandava o mês certo e mascarava o
    defeito; quem chama a API sem `billing_month` (import, script, integração)
    caía nele por três horas todo dia.
    """
    return month_key(to_local(momento))


def month_bounds_utc(reference: date) -> tuple[datetime, datetime]:
    """Limites do mês de calendário LOCAL, expressos como instantes UTC.

    As colunas de data guardam instantes UTC (`datetime.now(UTC)`), mas o mês
    que o usuário enxerga é o do fuso dele. Comparar um contra o outro com
    `datetime.combine` ingênuo — como o caixa fazia — jogava uma renda recebida
    às 22h de 31/07 em São Paulo (gravada como `2026-08-01T01:00Z`) para o mês
    seguinte.

    Devolve instantes **naive em UTC**, porque as colunas do SQLite são naive e
    comparar naive com aware levanta TypeError.
    """
    tz = app_tz()
    ultimo = calendar.monthrange(reference.year, reference.month)[1]
    inicio = datetime.combine(
        date(reference.year, reference.month, 1), time.min, tzinfo=tz
    )
    fim = datetime.combine(
        date(reference.year, reference.month, ultimo), time.max, tzinfo=tz
    )
    return (
        inicio.astimezone(UTC).replace(tzinfo=None),
        fim.astimezone(UTC).replace(tzinfo=None),
    )


def parse_month(month: Optional[str], *, default: Optional[date] = None) -> date:
    """`YYYY-MM` → 1º dia do mês. Vazio → `default` (ou hoje).

    Ponto ÚNICO de interpretação de mês. Antes havia quatro implementações com
    comportamentos diferentes para entrada inválida: três devolviam 400 e a de
    `/income` engolia o erro e IGNORAVA o filtro — devolvendo o histórico
    inteiro como se fosse o mês pedido, com o total do cabeçalho errado e nenhum
    sinal para o usuário.
    """
    if not month:
        return default or today_local()
    try:
        year_str, month_str = month.split("-")
        return date(int(year_str), int(month_str), 1)
    except (ValueError, TypeError):
        raise InvalidMonth("Formato de mês inválido. Use YYYY-MM")


def month_key(reference: date) -> str:
    """`date` → `"YYYY-MM"`, o formato de `Transaction.billing_month`.

    O `billing_month` é a definição ÚNICA de "mês" das agregações de despesa. As
    janelas por `transaction_date` (um instante gravado em UTC) discordavam dele
    na virada do mês: uma despesa lançada às 22h do dia 31 em Brasília tem
    `transaction_date` já no dia 1 do mês seguinte, então aparecia em Lançamentos
    e nas Dívidas de julho e nos Relatórios de agosto — a mesma despesa, na mesma
    sessão, em dois meses diferentes.
    """
    return f"{reference.year:04d}-{reference.month:02d}"


def month_bounds(reference: date) -> tuple[datetime, datetime]:
    """Primeiro instante e último instante do mês de `reference`."""
    last_day = calendar.monthrange(reference.year, reference.month)[1]
    start = datetime.combine(date(reference.year, reference.month, 1), datetime.min.time())
    end = datetime.combine(date(reference.year, reference.month, last_day), datetime.max.time())
    return start, end


def add_months(when: D, months: int) -> D:
    """Avança `months` meses preservando o dia (limitado ao último do mês alvo).

    Ex.: add_months(31/jan, 1) → 28/fev; add_months(15/dez, 1) → 15/jan do
    ano seguinte. Funciona para date e datetime (preserva hora/tz do datetime).
    """
    month_index = when.month - 1 + months
    year = when.year + month_index // 12
    month = month_index % 12 + 1
    day = min(when.day, calendar.monthrange(year, month)[1])
    return when.replace(year=year, month=month, day=day)
