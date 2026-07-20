from datetime import datetime, UTC
from typing import Optional
from decimal import Decimal
from sqlmodel import SQLModel, Field

class IncomeBase(SQLModel):
    title: str = Field(index=True)
    description: Optional[str] = None
    amount: Decimal = Field(decimal_places=2, max_digits=20)
    currency: str = Field(default="BRL")
    received_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    category: Optional[str] = Field(default=None, index=True) # e.g., "Salary", "Freelance"

class Income(IncomeBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    deleted_at: Optional[datetime] = Field(default=None)
