from datetime import datetime, UTC
from enum import Enum
from typing import Optional, List, TYPE_CHECKING
from decimal import Decimal
from sqlalchemy import JSON, Column
from sqlmodel import SQLModel, Field, Relationship

from app.models.transaction import PaymentMethod

if TYPE_CHECKING:
    from app.models.transaction import Transaction

class RecurrenceFrequency(str, Enum):
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"
    yearly = "yearly"

class RecurringExpenseBase(SQLModel):
    title: str = Field(index=True)
    description: Optional[str] = None
    base_amount: Decimal = Field(decimal_places=2, max_digits=20)
    frequency: RecurrenceFrequency = Field(default=RecurrenceFrequency.monthly)
    day_of_month: int = Field(ge=1, le=31)  # monthly/yearly
    day_of_week: Optional[int] = Field(default=None, ge=0, le=6)  # weekly (0=segunda)
    month_of_year: Optional[int] = Field(default=None, ge=1, le=12)  # yearly
    is_active: bool = Field(default=True)

class RecurringExpense(RecurringExpenseBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    created_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")

    # Snapshot completo (ADR 0012): a instância materializada nasce COMPLETA
    # (pagador + divisão + categoria + método + moeda), então entra em
    # dívidas/relatórios como qualquer despesa — sem isso a recorrência gerava
    # transação nua (REC-001).
    currency: str = Field(default="BRL")
    payment_method: Optional[PaymentMethod] = Field(default=None)
    category_id: Optional[int] = Field(default=None, foreign_key="category.id")
    payer_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    # Lista de {user_id, split_method, input_value}; None → divisão 100% ao pagador
    split_snapshot: Optional[list] = Field(default=None, sa_column=Column(JSON))

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    transactions: List["Transaction"] = Relationship(back_populates="recurring_expense")
