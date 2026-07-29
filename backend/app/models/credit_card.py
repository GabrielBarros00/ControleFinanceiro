from datetime import datetime, UTC
from enum import Enum
from typing import Optional, List
from decimal import Decimal
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint

class StatementStatus(str, Enum):
    open = "open"
    closed = "closed"
    paid = "paid"
    # LEGADO — nunca é atribuído. "Vencida" é DERIVADO na leitura
    # (`CreditCardService.is_overdue`), justamente para não depender de um job
    # que carimbe o estado. O rótulo continua no enum porque ele existe no tipo
    # nativo do Postgres e removê-lo exigiria recriar o tipo numa coluna em uso —
    # risco que não se paga por um valor que ninguém grava.
    overdue = "overdue"

class CreditCardBase(SQLModel):
    name: str = Field(index=True)
    limit: Decimal = Field(decimal_places=2, max_digits=20)
    closing_day: int = Field(ge=1, le=31)
    due_day: int = Field(ge=1, le=31)
    currency: str = Field(default="BRL")

class CreditCard(CreditCardBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    deleted_at: Optional[datetime] = Field(default=None)

    statements: List["CardStatement"] = Relationship(back_populates="card")

class CardStatementBase(SQLModel):
    month: str = Field(index=True)  # Format YYYY-MM
    closing_date: datetime
    due_date: datetime
    status: StatementStatus = Field(default=StatementStatus.open)
    # total_amount é CONGELADO no fechamento (ADR 0011): enquanto open, o total
    # autoritativo é calculado no servidor (soma das transações realizadas);
    # ao fechar, gravamos o valor faturado aqui para que o histórico não mude
    # se uma transação for reeditada depois.
    total_amount: Decimal = Field(default=Decimal("0.00"), decimal_places=2, max_digits=20)

class CardStatement(CardStatementBase, table=True):
    # Uma fatura por cartão/mês: derivação server-side conta com isso (ADR 0002)
    __table_args__ = (UniqueConstraint("card_id", "month", name="uq_statement_card_month"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    card_id: int = Field(foreign_key="creditcard.id", index=True)

    # Ciclo open→closed→paid + reabertura (ADR 0011)
    closed_at: Optional[datetime] = Field(default=None)
    paid_at: Optional[datetime] = Field(default=None)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    card: CreditCard = Relationship(back_populates="statements")
    payments: List["StatementPayment"] = Relationship(back_populates="statement")


class StatementPayment(SQLModel, table=True):
    """Pagamento de uma fatura, com a CONTA de onde o dinheiro saiu (ADR 0011).

    NÃO é uma Transaction/despesa: as compras do cartão já compõem o total da
    fatura e já entram em dívidas/relatórios. Registrar o pagamento como despesa
    faria contagem dobrada — exatamente o defeito que a auditoria combate. Aqui
    ele apenas registra origem/valor/data e libera o limite comprometido.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    statement_id: int = Field(foreign_key="cardstatement.id", index=True)
    account_id: Optional[int] = Field(default=None, foreign_key="paymentaccount.id", index=True)
    amount: Decimal = Field(decimal_places=2, max_digits=20)
    paid_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    note: Optional[str] = None
    created_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    deleted_at: Optional[datetime] = Field(default=None)

    statement: CardStatement = Relationship(back_populates="payments")
