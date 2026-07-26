from typing import Optional
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field

from app.schemas.common import DESCRIPTION_MAX, MAX_MONEY, TITLE_MAX

class IncomeBase(BaseModel):
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    amount: Decimal
    currency: str = "BRL"
    received_at: datetime
    category: Optional[str] = None

class IncomeCreate(IncomeBase):
    amount: Decimal = Field(gt=0, le=MAX_MONEY)

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
