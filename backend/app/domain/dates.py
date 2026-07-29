"""Aritmética de datas por MÊS DE CALENDÁRIO (não 30 dias).

Parcelamento, financiamento e recorrência avançam por mês real — somar
`timedelta(days=30)` desloca o vencimento e erra o rótulo de mês.
"""
import calendar
from datetime import date, datetime
from typing import Optional, TypeVar

D = TypeVar("D", date, datetime)


class InvalidMonth(ValueError):
    """Mês fora do formato YYYY-MM (o chamador traduz para 400)."""


def parse_month(month: Optional[str], *, default: Optional[date] = None) -> date:
    """`YYYY-MM` → 1º dia do mês. Vazio → `default` (ou hoje).

    Ponto ÚNICO de interpretação de mês. Antes havia quatro implementações com
    comportamentos diferentes para entrada inválida: três devolviam 400 e a de
    `/income` engolia o erro e IGNORAVA o filtro — devolvendo o histórico
    inteiro como se fosse o mês pedido, com o total do cabeçalho errado e nenhum
    sinal para o usuário.
    """
    if not month:
        return default or date.today()
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
