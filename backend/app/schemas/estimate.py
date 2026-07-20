from typing import Optional
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field

class MonthlyEstimateBase(BaseModel):
    category: str
    amount: Decimal
    month: str # YYYY-MM
    description: Optional[str] = None
    category_id: Optional[int] = None

class MonthlyEstimateCreate(MonthlyEstimateBase):
    amount: Decimal = Field(ge=0)
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")

class MonthlyEstimateRead(MonthlyEstimateBase):
    id: int
    workspace_id: int
    user_id: int
    created_at: datetime
    updated_at: datetime
