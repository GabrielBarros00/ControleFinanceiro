from typing import Optional
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field

from app.schemas.common import DESCRIPTION_MAX, MAX_MONEY, TITLE_MAX

class IncomeBase(BaseModel):
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    amount: Decimal
    # Default de LEITURA apenas (IncomeRead herda daqui e a coluna é NOT NULL).
    # Em qualquer schema de ENTRADA sobrescreva com `Optional[str] = None` e
    # resolva na rota com `resolve_currency` — ver IncomeCreate. Um "BRL" fixo na
    # entrada faz um workspace em outra moeda tratar toda renda como estrangeira.
    currency: str = "BRL"
    received_at: datetime
    category: Optional[str] = None

class IncomeCreate(IncomeBase):
    amount: Decimal = Field(gt=0, le=MAX_MONEY)
    # None = "não informada" → a rota resolve para a moeda-base do workspace
    currency: Optional[str] = None

class IncomeUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=TITLE_MAX)
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    amount: Optional[Decimal] = Field(default=None, gt=0, le=MAX_MONEY)
    currency: Optional[str] = None
    received_at: Optional[datetime] = None
    category: Optional[str] = None

class IncomeRead(IncomeBase):
    id: int
    workspace_id: int
    user_id: int
    recurring_income_id: Optional[int] = None
    billing_month: Optional[str] = None
    original_amount: Optional[Decimal] = None
    original_currency: Optional[str] = None
    exchange_rate: Optional[Decimal] = None
    rate_source: Optional[str] = None
    created_at: datetime
    updated_at: datetime
