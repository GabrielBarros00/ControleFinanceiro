from datetime import datetime, date, UTC
from enum import Enum
from typing import Optional, List, TYPE_CHECKING
from decimal import Decimal
from sqlalchemy import event, Index
from sqlalchemy.orm import attributes
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint

from app.models.tag import Tag, TransactionTagLink

if TYPE_CHECKING:
    from app.models.recurring import RecurringExpense

class TransactionStatus(str, Enum):
    draft = "draft"
    pending = "pending"
    confirmed = "confirmed"
    paid = "paid"
    cancelled = "cancelled"

class SplitMethod(str, Enum):
    equal = "equal"
    percentage = "percentage"
    fixed = "fixed"

class SplitMode(str, Enum):
    transaction = "transaction"  # divisão definida no nível da despesa
    item = "item"                # divisão derivada das shares de cada item

class PaymentMethod(str, Enum):
    credit_card = "credit_card"
    debit_card = "debit_card"
    pix = "pix"
    cash = "cash"
    bank_transfer = "bank_transfer"
    boleto = "boleto"
    other = "other"

class AdjustmentType(str, Enum):
    discount = "discount"    # desconto/cupom (negativo)
    tax = "tax"              # imposto/taxa (positivo)
    tip = "tip"              # gorjeta (positivo)
    shipping = "shipping"    # frete (positivo)
    cashback = "cashback"    # cashback (negativo)
    rounding = "rounding"    # arredondamento da nota (qualquer sinal)
    other = "other"

class TransactionBase(SQLModel):
    title: str = Field(index=True)
    description: Optional[str] = None
    currency: str = Field(default="BRL")
    total_amount: Decimal = Field(decimal_places=2, max_digits=20)
    transaction_date: datetime = Field(default_factory=lambda: datetime.now(UTC))
    billing_month: Optional[str] = Field(default=None, index=True) # Formato YYYY-MM
    status: TransactionStatus = Field(default=TransactionStatus.confirmed)
    split_mode: SplitMode = Field(default=SplitMode.transaction)
    payment_method: Optional[PaymentMethod] = Field(default=None, index=True)

class Transaction(TransactionBase, table=True):
    # uq(recurring, occurrence_date): uma instância por ocorrência da recorrência.
    # A instância excluída mantém a linha (tombstone) e ocupa a vaga → a unique
    # bloqueia recriação por natureza (ADR 0012). Transações comuns têm
    # occurrence_date NULL e não colidem (NULLs são distintos na unique).
    # Índice único (não constraint) para casar com o schema das migrações
    # (o banco sempre teve isto como UNIQUE INDEX uq_recurring_occurrence).
    __table_args__ = (
        Index("uq_recurring_occurrence", "recurring_expense_id", "occurrence_date", unique=True),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    # Indexado porque entra no predicado de envolvimento (ADR 0018), que agora
    # roda em TODA listagem de lançamento
    created_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    recurring_expense_id: Optional[int] = Field(default=None, foreign_key="recurringexpense.id", index=True)
    occurrence_date: Optional[date] = Field(default=None)
    # Despesa gerada ao PAGAR uma parcela de financiamento. O vínculo era o
    # TÍTULO ("Casa — Parcela 3/60"): renomear o financiamento fazia o estorno
    # não achar a despesa (que ficava para sempre no caixa), e uma despesa manual
    # homônima era apagada junto. Identidade resolve os dois.
    financing_installment_id: Optional[int] = Field(
        default=None, foreign_key="amortizationinstallment.id", index=True
    )
    
    # Credit Card links
    credit_card_id: Optional[int] = Field(default=None, foreign_key="creditcard.id", index=True)
    statement_id: Optional[int] = Field(default=None, foreign_key="cardstatement.id", index=True)

    # Parcelamento: N transações irmãs compartilham o mesmo group_id
    installment_no: Optional[int] = Field(default=None)
    installments_of: Optional[int] = Field(default=None)
    installment_group_id: Optional[str] = Field(default=None, index=True)

    # Conversão de moeda (ADR 0006 revisitado): lançamento estrangeiro é
    # convertido para a moeda-base na ENTRADA — total_amount/currency ficam em
    # BRL e os campos abaixo guardam o original (PTAX do dia + IOF congelados)
    # só para exibição. None = lançamento nativo em BRL.
    original_amount: Optional[Decimal] = Field(default=None, decimal_places=2, max_digits=20)
    original_currency: Optional[str] = Field(default=None)
    exchange_rate: Optional[Decimal] = Field(default=None, decimal_places=6, max_digits=20)
    iof_rate: Optional[Decimal] = Field(default=None, decimal_places=6, max_digits=8)
    # Fonte da taxa: 'ptax' (oficial) | 'market' (referência) | None (BRL nativo)
    rate_source: Optional[str] = Field(default=None)

    confirmed_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    deleted_at: Optional[datetime] = None

    # Relacionamentos
    payers: List["TransactionPayer"] = Relationship(back_populates="transaction")
    splits: List["TransactionSplit"] = Relationship(back_populates="transaction")
    items: List["TransactionItem"] = Relationship(back_populates="transaction")
    adjustments: List["TransactionAdjustment"] = Relationship(back_populates="transaction")
    tags: List[Tag] = Relationship(link_model=TransactionTagLink)
    recurring_expense: Optional["RecurringExpense"] = Relationship(back_populates="transactions")


class TransactionAdjustment(SQLModel, table=True):
    """Reconciliação com documentos reais: total = soma(itens) + soma(ajustes).

    amount tem SINAL explícito: desconto/cashback negativos, taxa/gorjeta/
    frete positivos, arredondamento livre.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    transaction_id: int = Field(foreign_key="transaction.id", index=True)
    type: AdjustmentType = Field(default=AdjustmentType.other)
    description: Optional[str] = None
    amount: Decimal = Field(decimal_places=2, max_digits=20)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    transaction: Transaction = Relationship(back_populates="adjustments")

class TransactionItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    transaction_id: int = Field(foreign_key="transaction.id", index=True)
    title: str
    description: Optional[str] = None
    amount: Decimal = Field(decimal_places=2, max_digits=20)  # total da linha
    quantity: Decimal = Field(default=Decimal("1"), decimal_places=3, max_digits=12)
    unit_amount: Optional[Decimal] = Field(default=None, decimal_places=2, max_digits=20)
    position: int = Field(default=0)
    category_id: Optional[int] = Field(default=None, foreign_key="category.id", index=True)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    transaction: Transaction = Relationship(back_populates="items")
    shares: List["TransactionItemShare"] = Relationship(back_populates="item")

class TransactionItemShare(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("item_id", "user_id", name="uq_itemshare_item_user"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="transactionitem.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    split_method: SplitMethod = Field(default=SplitMethod.equal)
    input_value: Decimal = Field(decimal_places=2, max_digits=20)  # % ou valor fixo
    computed_amount: Decimal = Field(decimal_places=2, max_digits=20)  # parte real do item

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    item: TransactionItem = Relationship(back_populates="shares")

class TransactionPayer(SQLModel, table=True):
    """Quem pagou, quanto e DE ONDE saiu o dinheiro (ADR 0004).

    payment_method/account_id por pagador: dois pagadores podem usar meios
    diferentes. Sem método próprio, herda o da transação (resumo/filtro).
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    transaction_id: int = Field(foreign_key="transaction.id", index=True)
    # Indexado pelo predicado de envolvimento (ADR 0018)
    user_id: int = Field(foreign_key="user.id", index=True)
    amount: Decimal = Field(decimal_places=2, max_digits=20)
    payment_method: Optional[PaymentMethod] = Field(default=None)
    account_id: Optional[int] = Field(default=None, foreign_key="paymentaccount.id", index=True)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    transaction: Transaction = Relationship(back_populates="payers")

class TransactionSplit(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    transaction_id: int = Field(foreign_key="transaction.id", index=True)
    # Indexado pelo predicado de envolvimento (ADR 0018)
    user_id: int = Field(foreign_key="user.id", index=True)
    split_method: SplitMethod = Field(default=SplitMethod.equal)
    input_value: Decimal = Field(decimal_places=2, max_digits=20) # Porcentagem ou Valor fixo
    computed_amount: Decimal = Field(decimal_places=2, max_digits=20) # Valor real em dinheiro

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    transaction: Transaction = Relationship(back_populates="splits")


def _stamp_status(target: Transaction, status: TransactionStatus, now: datetime) -> None:
    if status == TransactionStatus.confirmed and target.confirmed_at is None:
        target.confirmed_at = now
    elif status == TransactionStatus.paid and target.paid_at is None:
        target.paid_at = now
    elif status == TransactionStatus.cancelled and target.cancelled_at is None:
        target.cancelled_at = now


@event.listens_for(Transaction, "before_insert")
def _transaction_stamp_on_insert(mapper, connection, target: Transaction) -> None:
    # Listener de Mapper: cobre TODOS os caminhos de criação (manual, bulk,
    # recorrência, import) sem depender de cada rota lembrar do carimbo
    _stamp_status(target, target.status, datetime.now(UTC))
    # billing_month é o MÊS ÚNICO das agregações (dívidas, relatórios, previsão,
    # extrato). A coluna é nullable e uma linha sem ela sumiria de todas elas de
    # uma vez. Hoje os caminhos de criação preenchem — mas isso é disciplina de
    # quem escreve o código, não uma garantia. Aqui vira invariante: sem valor
    # explícito, deriva da data. O valor explícito continua vencendo.
    #
    # **Sem conversão de fuso, de propósito.** Aqui a PROVENIÊNCIA é
    # desconhecida: `transaction_date` chega ora como instante de verdade (o
    # cliente manda `new Date().toISOString()`), ora como data de CALENDÁRIO à
    # meia-noite (linha de CSV, cronograma, fixture). Converter às cegas move a
    # segunda para o dia anterior — `datetime(2026, 5, 1)` viraria competência de
    # abril. Quem SABE que recebeu um instante converte na entrada, com
    # `month_key_local` (ver `routes/transactions.py`).
    if not target.billing_month and target.transaction_date is not None:
        target.billing_month = target.transaction_date.strftime("%Y-%m")


@event.listens_for(Transaction, "before_update")
def _transaction_stamp_on_update(mapper, connection, target: Transaction) -> None:
    now = datetime.now(UTC)
    target.updated_at = now
    history = attributes.get_history(target, "status")
    if history.has_changes() and history.deleted:
        old_status = history.deleted[0]
        _stamp_status(target, target.status, now)
        # Reabertura (paid → confirmed): a despesa deixa de estar paga
        if old_status == TransactionStatus.paid and target.status == TransactionStatus.confirmed:
            target.paid_at = None
            target.confirmed_at = now
