from typing import Optional, List
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pydantic import BaseModel, Field, model_validator
from app.models.transaction import (
    AdjustmentType,
    TransactionStatus,
    SplitMethod,
    SplitMode,
    PaymentMethod,
)

class TransactionPayerBase(BaseModel):
    user_id: int
    amount: Decimal = Field(ge=0)
    # Origem por pagador (ADR 0004): cada um pode usar método/conta próprios;
    # sem método, herda o da transação (que segue como resumo/filtro)
    payment_method: Optional[PaymentMethod] = None
    account_id: Optional[int] = None

class TransactionSplitBase(BaseModel):
    user_id: int
    split_method: SplitMethod
    input_value: Decimal = Field(ge=0)

class TransactionItemShareBase(BaseModel):
    user_id: int
    split_method: SplitMethod
    input_value: Decimal = Field(default=Decimal("0"), ge=0)

class TransactionItemShareRead(TransactionItemShareBase):
    id: int
    computed_amount: Decimal

class TransactionItemBase(BaseModel):
    title: str
    description: Optional[str] = None
    amount: Decimal  # total da linha (fonte de verdade para somas)
    quantity: Decimal = Field(default=Decimal("1"), gt=0)
    unit_amount: Optional[Decimal] = Field(default=None, ge=0)
    position: int = 0
    category_id: Optional[int] = None

class TransactionItemCreate(TransactionItemBase):
    shares: Optional[List[TransactionItemShareBase]] = None

class TransactionItemRead(TransactionItemBase):
    id: int
    shares: List[TransactionItemShareRead] = []

class TransactionTagRead(BaseModel):
    id: int
    name: str
    color: Optional[str] = None


class TransactionAdjustmentBase(BaseModel):
    type: AdjustmentType = AdjustmentType.other
    description: Optional[str] = None
    amount: Decimal  # sinal explícito conforme o tipo


class TransactionAdjustmentCreate(TransactionAdjustmentBase):
    @model_validator(mode="after")
    def _validate_sign(self):
        if self.amount == 0:
            raise ValueError("Ajuste com valor zero não faz sentido — remova-o")
        if self.type in (AdjustmentType.discount, AdjustmentType.cashback) and self.amount > 0:
            raise ValueError(
                f"Ajuste '{self.type.value}' reduz o total — o valor deve ser negativo"
            )
        if self.type in (
            AdjustmentType.tax, AdjustmentType.tip, AdjustmentType.shipping
        ) and self.amount < 0:
            raise ValueError(
                f"Ajuste '{self.type.value}' aumenta o total — o valor deve ser positivo"
            )
        return self


class TransactionAdjustmentRead(TransactionAdjustmentBase):
    id: int

class TransactionBase(BaseModel):
    title: str
    description: Optional[str] = None
    currency: str = "BRL"
    total_amount: Decimal
    transaction_date: datetime
    billing_month: Optional[str] = None
    status: TransactionStatus = TransactionStatus.confirmed
    card_limit_holder_user_id: Optional[int] = None
    credit_card_id: Optional[int] = None
    split_mode: SplitMode = SplitMode.transaction
    payment_method: Optional[PaymentMethod] = None


def _ensure_unique_users(entries, context: str) -> None:
    seen = set()
    for entry in entries:
        if entry.user_id in seen:
            raise ValueError(f"Usuário repetido em {context}")
        seen.add(entry.user_id)


def _ensure_percent_range(entries, context: str) -> None:
    for entry in entries:
        if entry.split_method == SplitMethod.percentage and not (
            Decimal("0") < entry.input_value <= Decimal("100")
        ):
            raise ValueError(
                f"Percentual inválido em {context}: cada participante deve ficar entre 0 e 100"
            )


def _ensure_item_amounts(items: List["TransactionItemCreate"]) -> None:
    for item in items:
        if item.unit_amount is not None:
            expected = (item.quantity * item.unit_amount).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if item.amount != expected:
                raise ValueError(
                    f"Item '{item.title}': valor da linha ({item.amount}) difere de "
                    f"quantidade × valor unitário ({expected})"
                )


def validate_split_structure(
    split_mode: SplitMode,
    splits: List[TransactionSplitBase],
    items: Optional[List[TransactionItemCreate]],
) -> None:
    """Regras estruturais da matriz split_mode × splits/items.

    Compartilhada entre o validator do create e o caminho de edição completa
    (que precisa validar contra o split_mode EFETIVO, só conhecido na rota).
    Somas monetárias ficam no serviço (transaction_service).
    """
    if items:
        _ensure_item_amounts(items)

    if split_mode == SplitMode.transaction:
        if not splits:
            raise ValueError("Divisão pela despesa exige ao menos um participante em splits")
        if len({s.split_method for s in splits}) > 1:
            raise ValueError("Todos os splits devem usar o mesmo método de divisão")
        _ensure_unique_users(splits, "splits")
        _ensure_percent_range(splits, "splits")
        for item in items or []:
            if item.shares:
                raise ValueError(
                    f"Item '{item.title}' tem participantes, mas split_mode='transaction' — "
                    "use split_mode='item' para dividir por item"
                )
    else:
        if not items:
            raise ValueError("split_mode='item' exige ao menos um item")
        if splits:
            raise ValueError(
                "Com split_mode='item' os splits são derivados dos itens — envie splits vazio"
            )
        for item in items:
            if not item.shares:
                raise ValueError(f"Item '{item.title}' precisa de ao menos um participante")
            if len({s.split_method for s in item.shares}) > 1:
                raise ValueError(
                    f"Item '{item.title}': todos os participantes devem usar o mesmo método"
                )
            _ensure_unique_users(item.shares, f"item '{item.title}'")
            _ensure_percent_range(item.shares, f"item '{item.title}'")


def normalize_payment_method(
    payment_method: Optional[PaymentMethod],
    credit_card_id: Optional[int],
) -> Optional[PaymentMethod]:
    """Coerência método × cartão. Cartão presente sem método vira credit_card."""
    if credit_card_id is not None:
        if payment_method is None:
            return PaymentMethod.credit_card
        if payment_method != PaymentMethod.credit_card:
            raise ValueError(
                "Transação vinculada a cartão de crédito deve ter payment_method='credit_card'"
            )
    elif payment_method == PaymentMethod.credit_card:
        raise ValueError("payment_method='credit_card' exige um cartão (credit_card_id)")
    return payment_method


def validate_payer_origins(
    payers: List[TransactionPayerBase],
    credit_card_id: Optional[int],
) -> None:
    """Coerência da origem POR PAGADOR (ADR 0004) contra o cartão efetivo.

    Compartilhada entre create (validator) e edição completa (rota, que só
    conhece o cartão efetivo em runtime). Existência/workspace da conta é
    validada no serviço (precisa de sessão).
    """
    for payer in payers:
        if payer.payment_method == PaymentMethod.credit_card:
            if credit_card_id is None:
                raise ValueError(
                    "Pagador com método 'credit_card' exige um cartão na transação"
                )
            if payer.account_id is not None:
                raise ValueError(
                    "Pagamento no cartão de crédito não sai de uma conta — remova a conta do pagador"
                )


class TransactionCreate(TransactionBase):
    # Entrada validada: valor sempre positivo (leituras herdam a Base sem gt)
    total_amount: Decimal = Field(gt=0)
    payers: List[TransactionPayerBase]
    splits: List[TransactionSplitBase] = []
    items: Optional[List[TransactionItemCreate]] = None
    adjustments: Optional[List[TransactionAdjustmentCreate]] = None
    tag_ids: Optional[List[int]] = None
    # Parcelamento no cartão: cria N transações irmãs em meses sucessivos
    installments_count: Optional[int] = Field(default=None, ge=2, le=36)

    @model_validator(mode="after")
    def _validate_structure(self):
        _ensure_unique_users(self.payers, "payers")
        validate_split_structure(self.split_mode, self.splits, self.items)
        self.payment_method = normalize_payment_method(self.payment_method, self.credit_card_id)
        validate_payer_origins(self.payers, self.credit_card_id)

        if self.adjustments and not self.items:
            raise ValueError(
                "Ajustes reconciliam itens com o total — informe os itens da despesa"
            )
        if self.adjustments and self.installments_count:
            raise ValueError("Parcelamento não suporta ajustes de total")

        if self.installments_count:
            if self.payment_method != PaymentMethod.credit_card:
                raise ValueError("Parcelamento exige pagamento no cartão de crédito")
            if len(self.payers) != 1:
                raise ValueError("Parcelamento exige um único pagador")
            # Parcelar = fatiar a divisão pelos N meses; item/porcentagem/valor
            # fixo são suportados pelo motor de parcelas. No modo transaction só
            # entra o item-categoria (sem shares, valor == total) — itens
            # detalhados exigem split_mode='item'.
            if self.split_mode == SplitMode.transaction and self.items and (
                len(self.items) > 1
                or self.items[0].shares
                or self.items[0].amount != self.total_amount
            ):
                raise ValueError(
                    "Parcelamento pela despesa não suporta itens detalhados — use divisão por item"
                )
        return self

class TransactionPayerRead(TransactionPayerBase):
    id: int

class TransactionSplitRead(TransactionSplitBase):
    id: int
    computed_amount: Decimal

class TransactionRead(TransactionBase):
    id: int
    workspace_id: int
    # Somente leitura: a fatura é SEMPRE derivada no servidor (ADR 0002)
    statement_id: Optional[int] = None
    created_by_user_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    installment_no: Optional[int] = None
    installments_of: Optional[int] = None
    installment_group_id: Optional[str] = None
    payers: List[TransactionPayerRead]
    splits: List[TransactionSplitRead]
    items: List[TransactionItemRead] = []
    adjustments: List[TransactionAdjustmentRead] = []
    tags: List[TransactionTagRead] = []

class TransactionUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    total_amount: Optional[Decimal] = Field(default=None, gt=0)
    transaction_date: Optional[datetime] = None
    billing_month: Optional[str] = None
    status: Optional[TransactionStatus] = None
    credit_card_id: Optional[int] = None
    payment_method: Optional[PaymentMethod] = None
    # Categoria simplificada: upsert do item único da transação
    category_id: Optional[int] = None
    tag_ids: Optional[List[int]] = None
    # Edição completa da divisão: se qualquer um destes vier, a rota exige o
    # conjunto completo e recria payers/splits/items/ajustes atomicamente
    split_mode: Optional[SplitMode] = None
    payers: Optional[List[TransactionPayerBase]] = None
    splits: Optional[List[TransactionSplitBase]] = None
    items: Optional[List[TransactionItemCreate]] = None
    adjustments: Optional[List[TransactionAdjustmentCreate]] = None

    @model_validator(mode="after")
    def _validate_structure(self):
        if self.items is not None and self.category_id is not None:
            raise ValueError("Envie items OU category_id — nunca os dois")
        if self.payers is not None:
            _ensure_unique_users(self.payers, "payers")
        return self

class TransactionListResponse(BaseModel):
    items: List[TransactionRead]
    total: int
    page: int
    limit: int
    total_pages: int
