"""Entrada da despesa RECORRENTE do espaço (ADR 0012/0030/0032).

Morava em `api/routes/recurring.py` até o ADR 0035: os comandos de criar e
editar foram para `services/commands/recurring.py` (compartilhados com o MCP) e
um serviço não importa de rota. Mesmos nomes, então o OpenAPI não muda.
"""
from datetime import date
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.recurring import RecurrenceFrequency
from app.models.transaction import (
    STATEMENT_SHIFT_MAX,
    STATEMENT_SHIFT_MIN,
    PaymentMethod,
    SplitMethod,
)
from app.schemas.common import DESCRIPTION_MAX, MAX_MONEY, OptionalCurrencyCode, TITLE_MAX


class RecurringSplitEntry(BaseModel):
    user_id: int
    split_method: SplitMethod = SplitMethod.equal
    input_value: Decimal = Field(default=Decimal("0"), ge=0, le=MAX_MONEY)


class RecurringCreate(BaseModel):
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    base_amount: Decimal = Field(gt=0, le=MAX_MONEY)
    frequency: RecurrenceFrequency = RecurrenceFrequency.monthly
    interval: int = Field(default=1, ge=1)
    start_date: Optional[date] = None
    # Fim da série (ADR 0030). `end_after_occurrences` é a mesma coisa dita de
    # outro jeito ("por 144 vezes") e o servidor a converte em `end_date`; só
    # esta última é persistida, para não haver duas verdades sobre quando acaba.
    end_date: Optional[date] = None
    end_after_occurrences: Optional[int] = Field(default=None, ge=1, le=600)
    day_of_month: int = Field(default=1, ge=1, le=31)
    day_of_week: Optional[int] = Field(default=None, ge=0, le=6)
    month_of_year: Optional[int] = Field(default=None, ge=1, le=12)
    # Snapshot (ADR 0012): materializa despesa completa em vez de nua
    # None = "não informada" → a rota resolve para a moeda-base do workspace
    currency: OptionalCurrencyCode = None
    payment_method: Optional[PaymentMethod] = None
    # "Pagamento automático" (ADR 0029): débito em conta, Pix automático. A
    # ocorrência nasce liquidada e não entra em Contas a pagar.
    auto_settle: bool = False
    credit_card_id: Optional[int] = None
    # Deslocamento de fatura do template (ADR 0032). Uma assinatura cobrada perto
    # do fechamento cai na fatura seguinte TODO mês — é característica do
    # cobrador, e declará-la uma vez evita corrigir cada ocorrência à mão.
    statement_shift: int = Field(
        default=0, ge=STATEMENT_SHIFT_MIN, le=STATEMENT_SHIFT_MAX
    )
    category_id: Optional[int] = None
    payer_user_id: Optional[int] = None
    split_snapshot: Optional[List[RecurringSplitEntry]] = None


class RecurringUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=TITLE_MAX)
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    base_amount: Optional[Decimal] = Field(default=None, gt=0, le=MAX_MONEY)
    frequency: Optional[RecurrenceFrequency] = None
    interval: Optional[int] = Field(default=None, ge=1)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    end_after_occurrences: Optional[int] = Field(default=None, ge=1, le=600)
    day_of_month: Optional[int] = Field(default=None, ge=1, le=31)
    day_of_week: Optional[int] = Field(default=None, ge=0, le=6)
    month_of_year: Optional[int] = Field(default=None, ge=1, le=12)
    is_active: Optional[bool] = None
    currency: OptionalCurrencyCode = None
    payment_method: Optional[PaymentMethod] = None
    auto_settle: Optional[bool] = None
    credit_card_id: Optional[int] = None
    statement_shift: Optional[int] = Field(
        default=None, ge=STATEMENT_SHIFT_MIN, le=STATEMENT_SHIFT_MAX
    )
    category_id: Optional[int] = None
    payer_user_id: Optional[int] = None
    split_snapshot: Optional[List[RecurringSplitEntry]] = None
