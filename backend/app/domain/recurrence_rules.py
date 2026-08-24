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
    end_date: Optional[date] = None,
) -> None:
    # Fim antes do início não é série vazia por engano — é entrada contraditória,
    # e aceitá-la criaria uma recorrência ativa que nunca gera nada e ninguém
    # entende por quê (ADR 0030).
    if end_date is not None and start_date is not None and end_date < start_date:
        raise HTTPException(
            status_code=400,
            detail="A data de término não pode ser anterior à data de início",
        )
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
