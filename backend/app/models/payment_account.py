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

    Conta bancária é de UMA pessoa (ADR 0021): sem `workspace_id`, e o dono é
    obrigatório. A conta acompanha o dono em todo workspace de que ele participa e
    não é visível a mais ninguém. O `owner_user_id` opcional de antes significava
    "conta da casa" e tornava o extrato bancário de alguém um recurso coletivo.

    A unicidade do nome passa a ser POR DONO: duas pessoas podem ter uma conta
    "Nubank" cada, e o mesmo dono não pode ter duas.
    """

    __table_args__ = (
        UniqueConstraint("owner_user_id", "name", name="uq_paymentaccount_owner_name"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    owner_user_id: int = Field(foreign_key="user.id", index=True)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    deleted_at: Optional[datetime] = Field(default=None)
