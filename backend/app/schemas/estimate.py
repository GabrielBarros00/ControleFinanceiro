from typing import Optional
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field

from app.schemas.common import DESCRIPTION_MAX, MAX_MONEY, NAME_MAX

class MonthlyEstimateBase(BaseModel):
    category: str = Field(max_length=NAME_MAX)
    amount: Decimal
    month: str # YYYY-MM
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    category_id: Optional[int] = None

class MonthlyEstimateCreate(MonthlyEstimateBase):
    amount: Decimal = Field(ge=0, le=MAX_MONEY)
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")

class MonthlyEstimateRead(MonthlyEstimateBase):
    id: int
    workspace_id: int
    user_id: int
    created_at: datetime
    updated_at: datetime
