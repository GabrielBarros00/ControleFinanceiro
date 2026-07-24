from typing import Optional
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field

class IncomeBase(BaseModel):
    title: str
    description: Optional[str] = None
    amount: Decimal
    currency: str = "BRL"
    received_at: datetime
    category: Optional[str] = None

class IncomeCreate(IncomeBase):
    amount: Decimal = Field(gt=0)

class IncomeUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[Decimal] = Field(default=None, gt=0)
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
