"""Regras compartilhadas de recorrência (despesa e renda).

`_validate_frequency_fields` existia em DUAS cópias idênticas, uma em cada rota.
Mantê-las em sincronia era manual — e a validação de frequência é justamente o
lugar onde uma divergência silenciosa gera ocorrência materializada errada.
"""
from datetime import date
from typing import Optional

from fastapi import HTTPException

from app.models.recurring import RecurrenceFrequency


def validate_frequency_fields(
    frequency: RecurrenceFrequency,
    day_of_week: Optional[int],
    month_of_year: Optional[int],
    interval: int = 1,
    start_date: Optional[date] = None,
) -> None:
    # Personalizado (a cada N>1): tudo deriva de start_date, que passa a ser exigido
    if interval and interval > 1:
        if start_date is None:
            raise HTTPException(
                status_code=400,
                detail="Recorrência personalizada (a cada N) exige a data de início",
            )
        return
    if frequency == RecurrenceFrequency.weekly and day_of_week is None:
        raise HTTPException(status_code=400, detail="Recorrência semanal exige o dia da semana")
    if frequency == RecurrenceFrequency.yearly and month_of_year is None:
        raise HTTPException(status_code=400, detail="Recorrência anual exige o mês do ano")
