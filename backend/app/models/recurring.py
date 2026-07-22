from datetime import datetime, date, UTC
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
    # interval > 1 = "a cada N períodos" (personalizado); ancorado em start_date.
    # interval == 1 = preset (Diário/Semanal/Mensal/Anual), fase por day_of_* (legado).
    interval: int = Field(default=1, ge=1)
    start_date: Optional[date] = Field(default=None)
    day_of_month: int = Field(ge=1, le=31)  # monthly/yearly (preset)
    day_of_week: Optional[int] = Field(default=None, ge=0, le=6)  # weekly preset (0=segunda)
    month_of_year: Optional[int] = Field(default=None, ge=1, le=12)  # yearly preset
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


class RecurringIncomeBase(SQLModel):
    title: str = Field(index=True)
    description: Optional[str] = None
    base_amount: Decimal = Field(decimal_places=2, max_digits=20)
    currency: str = Field(default="BRL")
    category: Optional[str] = Field(default=None, index=True)  # ex.: "Salário"
    frequency: RecurrenceFrequency = Field(default=RecurrenceFrequency.monthly)
    interval: int = Field(default=1, ge=1)  # "a cada N" períodos (N>1 = personalizado)
    start_date: Optional[date] = Field(default=None)  # âncora do intervalo (N>1)
    day_of_month: int = Field(default=1, ge=1, le=31)  # monthly/yearly (preset)
    day_of_week: Optional[int] = Field(default=None, ge=0, le=6)  # weekly preset (0=segunda)
    month_of_year: Optional[int] = Field(default=None, ge=1, le=12)  # yearly preset
    is_active: bool = Field(default=True)


class RecurringIncome(RecurringIncomeBase, table=True):
    """Template de renda recorrente. Materializa entradas Income mensais
    (RecurringIncomeService.generate_due_income), espelhando RecurringExpense
    mas sem divisão/pagador (renda é pessoal)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    created_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    # Destinatário da renda (quem recebe); default = criador
    user_id: int = Field(foreign_key="user.id", index=True)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
