from datetime import datetime, UTC, date
from enum import Enum
from typing import Optional, List
from decimal import Decimal
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint

class AmortizationMethod(str, Enum):
    SAC = "SAC"
    PRICE = "PRICE"

class FinancingStatus(str, Enum):
    active = "active"
    settled = "settled"
    simulated = "simulated"

class FinancingBase(SQLModel):
    title: str = Field(index=True)
    description: Optional[str] = None
    total_amount: Decimal = Field(decimal_places=2, max_digits=20)
    interest_rate: Decimal = Field(decimal_places=6, max_digits=10) # Yearly or Monthly? Let's clarify in service.
    start_date: date
    installments_count: int = Field(ge=1)
    method: AmortizationMethod = Field(default=AmortizationMethod.SAC)
    status: FinancingStatus = Field(default=FinancingStatus.active)
    currency: str = Field(default="BRL")

class Financing(FinancingBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    created_by_user_id: int = Field(foreign_key="user.id")
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    deleted_at: Optional[datetime] = Field(default=None)

    schedule: List["AmortizationInstallment"] = Relationship(back_populates="financing")

class AmortizationInstallmentBase(SQLModel):
    installment_number: int
    due_date: date
    principal_amount: Decimal = Field(decimal_places=2, max_digits=20)
    interest_amount: Decimal = Field(decimal_places=2, max_digits=20)
    total_amount: Decimal = Field(decimal_places=2, max_digits=20)
    remaining_balance: Decimal = Field(decimal_places=2, max_digits=20)
    is_paid: bool = Field(default=False)

class AmortizationInstallment(AmortizationInstallmentBase, table=True):
    __table_args__ = (
        UniqueConstraint("financing_id", "installment_number", name="uq_amortization_financing_number"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    financing_id: int = Field(foreign_key="financing.id", index=True)
    paid_at: Optional[datetime] = None
    
    financing: Financing = Relationship(back_populates="schedule")
