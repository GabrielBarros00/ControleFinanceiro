from datetime import datetime, UTC
from enum import Enum
from typing import Optional
from sqlmodel import SQLModel, Field, UniqueConstraint


class PaymentAccountType(str, Enum):
    cash = "cash"                      # carteira em dinheiro
    checking = "checking"              # conta corrente
    savings = "savings"                # poupança
    digital_wallet = "digital_wallet"  # PicPay, Mercado Pago etc.
    other = "other"


class PaymentAccountBase(SQLModel):
    name: str = Field(index=True)
    type: PaymentAccountType = Field(default=PaymentAccountType.checking)
    currency: str = Field(default="BRL")
    active: bool = Field(default=True)


class PaymentAccount(PaymentAccountBase, table=True):
    """Origem do dinheiro (ADR 0004): de qual conta/carteira saiu um pagamento.

    Cartão de crédito NÃO é conta — é o relacionamento próprio (CreditCard).
    owner_user_id opcional: conta pessoal de um membro ou compartilhada (None).
    """

    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_paymentaccount_workspace_name"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    owner_user_id: Optional[int] = Field(default=None, foreign_key="user.id")

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    deleted_at: Optional[datetime] = Field(default=None)
