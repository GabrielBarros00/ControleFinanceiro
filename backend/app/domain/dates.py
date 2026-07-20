"""Aritmética de datas por MÊS DE CALENDÁRIO (não 30 dias).

Parcelamento, financiamento e recorrência avançam por mês real — somar
`timedelta(days=30)` desloca o vencimento e erra o rótulo de mês.
"""
import calendar
from datetime import date, datetime
from typing import TypeVar

D = TypeVar("D", date, datetime)


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
