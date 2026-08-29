from typing import Optional, List
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pydantic import BaseModel, Field, model_validator
from app.models.transaction import (
    STATEMENT_SHIFT_MAX,
    STATEMENT_SHIFT_MIN,
    AdjustmentType,
    TransactionStatus,
    SplitMethod,
    SplitMode,
    PaymentMethod,
)

from app.schemas.common import DESCRIPTION_MAX, MAX_MONEY, OptionalCurrencyCode, TITLE_MAX  # noqa: F401


class TransactionPayerBase(BaseModel):
    user_id: int
    amount: Decimal = Field(ge=0, le=MAX_MONEY)
    # Origem por pagador (ADR 0004): cada um pode usar método/conta próprios;
    # sem método, herda o da transação (que segue como resumo/filtro)
    payment_method: Optional[PaymentMethod] = None
    account_id: Optional[int] = None

class TransactionSplitBase(BaseModel):
    user_id: int
    split_method: SplitMethod
    input_value: Decimal = Field(ge=0, le=MAX_MONEY)

class TransactionItemShareBase(BaseModel):
    user_id: int
    split_method: SplitMethod
    input_value: Decimal = Field(default=Decimal("0"), ge=0)

class TransactionItemShareRead(TransactionItemShareBase):
    id: int
    computed_amount: Decimal

class TransactionItemBase(BaseModel):
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    # Total da linha (fonte de verdade p/ somas). `ge=0`: o item é uma LINHA da
    # nota, sempre positiva — quem reduz o total é o ajuste (desconto/cashback),
    # que tem sinal explícito e validador próprio. Sem o piso, um item negativo
    # passava pela borda e só era barrado indiretamente (e só no modo item, pelo
    # `Money`); no modo transaction ele fechava a conta e ia para o banco.
    amount: Decimal = Field(ge=0, le=MAX_MONEY)
    quantity: Decimal = Field(default=Decimal("1"), gt=0)
    unit_amount: Optional[Decimal] = Field(default=None, ge=0, le=MAX_MONEY)
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
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
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
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    # Default de LEITURA apenas (TransactionRead herda daqui e a coluna é NOT
    # NULL). Em qualquer schema de ENTRADA sobrescreva com `Optional[str] = None`
    # e resolva na rota com `resolve_currency` — ver TransactionCreate.
    currency: str = "BRL"
    total_amount: Decimal
    transaction_date: datetime
    billing_month: Optional[str] = None
    status: TransactionStatus = TransactionStatus.confirmed
    credit_card_id: Optional[int] = None
    # Deslocamento de fatura declarado (ADR 0032): quantas faturas à frente (ou
    # atrás) a compra realmente entrou, porque o emissor a processou noutro
    # ciclo. `0` = vale a regra do dia de fechamento.
    #
    # É a ÚNICA entrada do cliente que influencia o destino da fatura, e não
    # afrouxa o ADR 0002: continua sendo o servidor que resolve qual fatura é —
    # o cliente diz "uma para frente", nunca `statement_id`, então não há
    # como apontar para a fatura de outro cartão ou de outra pessoa.
    statement_shift: int = Field(
        default=0, ge=STATEMENT_SHIFT_MIN, le=STATEMENT_SHIFT_MAX
    )
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


def validate_statement_shift(
    statement_shift: int,
    credit_card_id: Optional[int],
) -> None:
    """Deslocar a fatura só faz sentido numa compra no cartão (ADR 0032).

    Compartilhada entre create (validator) e edição (rota, onde o cartão efetivo
    só é conhecido depois de mesclar o corpo parcial com a linha do banco).

    Sem esta guarda o campo seria aceito e ignorado num Pix — a API responderia
    200 e a coluna guardaria um deslocamento que nenhum roteamento leria. E o
    silêncio teria consequência real: ao converter esse lançamento para cartão
    mais tarde, o deslocamento esquecido acordaria e mandaria a compra para uma
    fatura que ninguém pediu.
    """
    if statement_shift and credit_card_id is None:
        raise ValueError(
            "Deslocamento de fatura exige uma compra no cartão (credit_card_id)"
        )


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
    total_amount: Decimal = Field(gt=0, le=MAX_MONEY)
    # None = "não informada" → a rota resolve para a moeda-base do workspace
    # (`resolve_currency`). Um default "BRL" aqui fazia um workspace em outra
    # moeda tratar toda despesa comum como estrangeira.
    currency: OptionalCurrencyCode = None
    payers: List[TransactionPayerBase]
    splits: List[TransactionSplitBase] = []
    items: Optional[List[TransactionItemCreate]] = None
    adjustments: Optional[List[TransactionAdjustmentCreate]] = None
    tag_ids: Optional[List[int]] = None
    # Parcelamento no cartão: cria N transações irmãs em meses sucessivos
    installments_count: Optional[int] = Field(default=None, ge=2, le=36)
    # "Já foi paga" (ADR 0029). `None` = não opinou, e a rota decide pela data
    # (`resolve_settled_at`): o que já venceu nasce liquidado, o que vence à
    # frente nasce a pagar. Não é o mesmo que `status`: aqui se fala de CAIXA,
    # lá de competência.
    settled: Optional[bool] = None

    @model_validator(mode="after")
    def _validate_structure(self):
        _ensure_unique_users(self.payers, "payers")
        validate_split_structure(self.split_mode, self.splits, self.items)
        self.payment_method = normalize_payment_method(self.payment_method, self.credit_card_id)
        validate_payer_origins(self.payers, self.credit_card_id)
        validate_statement_shift(self.statement_shift, self.credit_card_id)

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
    # Quando o dinheiro saiu de fato; `None` = ainda a pagar (ADR 0029). A tela
    # precisa do INSTANTE, não de um booleano: é ele que explica por que uma
    # despesa de julho aparece no caixa de agosto.
    settled_at: Optional[datetime] = None
    # Somente leitura: a fatura é SEMPRE derivada no servidor (ADR 0002)
    statement_id: Optional[int] = None
    created_by_user_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    installment_no: Optional[int] = None
    installments_of: Optional[int] = None
    installment_group_id: Optional[str] = None
    # Conversão de moeda (original congelado quando o lançamento foi estrangeiro)
    original_amount: Optional[Decimal] = None
    original_currency: Optional[str] = None
    exchange_rate: Optional[Decimal] = None
    iof_rate: Optional[Decimal] = None
    rate_source: Optional[str] = None
    payers: List[TransactionPayerRead]
    splits: List[TransactionSplitRead]
    items: List[TransactionItemRead] = []
    adjustments: List[TransactionAdjustmentRead] = []
    tags: List[TransactionTagRead] = []

class TransactionUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=TITLE_MAX)
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    total_amount: Optional[Decimal] = Field(default=None, gt=0, le=MAX_MONEY)
    # Moeda do lançamento na edição: estrangeira dispara reconversão para BRL
    currency: OptionalCurrencyCode = None
    transaction_date: Optional[datetime] = None
    billing_month: Optional[str] = None
    status: Optional[TransactionStatus] = None
    credit_card_id: Optional[int] = None
    # Mover a compra de fatura (ADR 0032). `None` = não mexe: um PUT que reenvia
    # o formulário inteiro para corrigir o título não pode rerrotear a fatura
    # sem querer — o mesmo cuidado que `settled` já tem logo abaixo.
    statement_shift: Optional[int] = Field(
        default=None, ge=STATEMENT_SHIFT_MIN, le=STATEMENT_SHIFT_MAX
    )
    payment_method: Optional[PaymentMethod] = None
    # Marcar/desmarcar como paga (ADR 0029). Ausente = não mexe — é um fato de
    # caixa, e uma edição de valor ou de divisão não pode ressuscitar nem apagar
    # um pagamento sem querer.
    settled: Optional[bool] = None
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
    # Soma do filtro inteiro (não só da página que veio) — a tela exibe esse
    # total ao lado da contagem, e as duas precisam falar da mesma amostra
    total_amount: Decimal = Decimal("0")
    page: int
    limit: int
    total_pages: int


# --------------------------------------------------------------------------
# Rotas que devolviam dict cru
# --------------------------------------------------------------------------

class BreakdownSplit(TransactionSplitBase):
    """Uma divisão JÁ CALCULADA: o que a pessoa efetivamente assume."""
    computed_amount: Decimal


class BreakdownItemShare(TransactionItemShareBase):
    computed_amount: Decimal


class BreakdownItem(TransactionItemBase):
    shares: List[BreakdownItemShare] = []


class TransactionPreviewRead(BaseModel):
    """Dry-run da criação: a divisão calculada, sem persistir nada.

    Sai da MESMA função do POST (`compute_transaction_breakdown`), então o que o
    preview mostra é exatamente o que será gravado — a razão de ele existir. No
    modo `item`, `splits` vem DERIVADO das shares (sempre `fixed`), que é como o
    banco também os grava.
    """
    payers: List[TransactionPayerBase] = []
    adjustments: List[TransactionAdjustmentBase] = []
    items: List[BreakdownItem] = []
    splits: List[BreakdownSplit] = []


class InstallmentGroupRead(BaseModel):
    """A compra parcelada vista como UMA compra (ADR: editar parcelada é editar
    a compra inteira).

    `group_total` soma as parcelas VIVAS, e é o número que o formulário de edição
    usa — por isso as irmãs não são reescopadas por visibilidade: um total
    parcial aqui é pior do que não mostrar.
    """
    installment_group_id: str
    installments_of: Optional[int] = None
    #: Quantas parcelas ainda existem (excluídas não contam).
    count_live: int
    #: Quantas já foram pagas — elas CONGELAM na edição do grupo.
    paid_count: int
    group_total: Decimal
    #: Título base, sem o sufixo "i/N".
    title: str
    #: A definição da compra inteira no formato de leitura, para o formulário
    #: pré-preencher o total cheio com a divisão certa.
    whole: TransactionRead


class BulkSkipped(BaseModel):
    index: int
    title: str
    reason: str


class BulkCreateResult(BaseModel):
    """Criação em lote — nada é descartado em silêncio (ADR 0008)."""
    status: str
    created: int
    skipped: int
    skipped_details: List[BulkSkipped] = []


class BulkDeleteResult(BaseModel):
    """Exclusão em lote. `skipped_paid` existe porque despesa PAGA é imutável
    (ADR 0003): ela é pulada, não recusada — senão um lote inteiro falharia por
    causa de uma linha."""
    status: str
    deleted: int
    skipped_paid: int


class InstallmentGroupCancelResult(BaseModel):
    """Cancelamento das parcelas FUTURAS de uma compra parcelada.

    `skipped_paid` existe porque despesa paga é imutável (ADR 0003): ela é
    pulada, não recusada — cancelar o resto de um carnê não pode falhar por
    causa das parcelas que já foram quitadas.
    """
    status: str
    cancelled: int
    skipped_paid: int
