from datetime import datetime, date, UTC
from enum import Enum
from typing import Optional, List, TYPE_CHECKING
from decimal import Decimal
from sqlalchemy import Column, Integer, event, Index, text
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

# Limites do deslocamento de fatura (ADR 0032). Vivem aqui, ao lado da coluna,
# porque tanto o schema de entrada quanto o serviço de roteamento precisam deles
# e `models` é a folha da árvore de imports — de qualquer outro lugar isto seria
# ciclo ou uma segunda cópia do intervalo.
#
# O intervalo é estreito DE PROPÓSITO. Atraso de captura é de 1 a 3 dias e nunca
# atravessa mais de um ciclo; −1 existe para o caso oposto (o emissor manteve na
# fatura que fechou no dia). Um campo livre transformaria um ajuste de borda numa
# forma de jogar despesa para qualquer mês do futuro — que é contabilidade
# criativa, não correção de processamento.
STATEMENT_SHIFT_MIN = -1
STATEMENT_SHIFT_MAX = 2


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

# Predicado do índice parcial abaixo. Fora da classe DE PROPÓSITO: um atributo
# no corpo de um modelo SQLModel é interpretado como campo, e um nome com
# underscore vira atributo privado do Pydantic — nos dois casos a tabela sai
# errada, sem erro na importação.
_DESPESA_DE_PARCELA_VIVA = text(
    "financing_installment_id IS NOT NULL AND deleted_at IS NULL"
)

# Predicado do índice de "contas a pagar" (ADR 0029). Fora da classe pelo mesmo
# motivo do de cima. Os três termos são exatamente o recorte da tela: o que ainda
# não foi liquidado, está vivo, e não é compra no cartão (essa vira caixa pela
# fatura, não por liquidação própria).
_A_LIQUIDAR = text(
    "settled_at IS NULL AND deleted_at IS NULL AND credit_card_id IS NULL"
)


class Transaction(TransactionBase, table=True):
    # uq(recurring, occurrence_date): uma instância por ocorrência da recorrência.
    # A instância excluída mantém a linha (tombstone) e ocupa a vaga → a unique
    # bloqueia recriação por natureza (ADR 0012). Transações comuns têm
    # occurrence_date NULL e não colidem (NULLs são distintos na unique).
    # Índice único (não constraint) para casar com o schema das migrações
    # (o banco sempre teve isto como UNIQUE INDEX uq_recurring_occurrence).
    #
    # uq_transaction_financing_installment: uma despesa VIVA por parcela de
    # financiamento. Segunda linha de defesa da reivindicação atômica em
    # `me_financing.pay_installment` — sem ela, qualquer caminho futuro que crie
    # a despesa sem reivindicar a parcela volta a duplicar caixa e relatórios.
    # PARCIAL, e `deleted_at IS NULL` é obrigatório no predicado:
    # `unpay_installment` faz SOFT delete e deixa o `financing_installment_id`
    # preenchido, então um unique simples proibiria o fluxo legítimo pagar →
    # estornar → pagar de novo.
    __table_args__ = (
        Index("uq_recurring_occurrence", "recurring_expense_id", "occurrence_date", unique=True),
        Index(
            "uq_transaction_financing_installment",
            "financing_installment_id",
            unique=True,
            sqlite_where=_DESPESA_DE_PARCELA_VIVA,
            postgresql_where=_DESPESA_DE_PARCELA_VIVA,
        ),
        Index(
            "ix_transaction_a_liquidar",
            "workspace_id",
            "billing_month",
            sqlite_where=_A_LIQUIDAR,
            postgresql_where=_A_LIQUIDAR,
        ),
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

    # DESLOCAMENTO DE CICLO DECLARADO (ADR 0032). Quantas faturas à frente (ou
    # atrás) esta compra entrou em relação ao que a regra do dia de fechamento
    # diz. `0` = a regra vale, que é o comportamento de sempre.
    #
    # Existe porque a fatura real é composta pela data de PROCESSAMENTO do
    # emissor, não pela data da compra: uma compra de 27/07 capturada pelo
    # estabelecimento em 30/07 entra na fatura de agosto, e o atraso é do
    # estabelecimento — o cartão não tem como prevê-lo. Antes disto a única
    # forma de mover uma compra de fatura era MENTIR na `transaction_date`, o
    # que arrastava junto a competência (`billing_month`), a data da cotação de
    # câmbio e a data exibida no extrato.
    #
    # RELATIVO, não absoluto (não é "a fatura de setembro"), por dois motivos que
    # um mês fixo não atende: numa compra parcelada o deslocamento vale para as N
    # parcelas, cada uma no seu ciclo; e numa recorrência ele vale para toda
    # ocorrência futura, que ainda nem tem mês. É também o que faz a correção
    # SOBREVIVER a uma edição de data — a fatura é rederivada e o deslocamento
    # se reaplica sobre o alvo novo.
    #
    # NOT NULL com default 0: é operando de soma em todo caminho de roteamento, e
    # um `None` obrigaria um `or 0` em cada um deles — a primeira omissão
    # devolveria um TypeError em produção, na criação de despesa.
    statement_shift: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )

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

    # A PERNA DE FATURA (ADR 0024). `currency`/`total_amount` acima são a perna
    # CONTÁBIL, na moeda-base do WORKSPACE; estes são o mesmo lançamento na moeda
    # do CARTÃO, que é onde a fatura é cobrada. None = lançamento sem cartão.
    #
    # As duas moedas são independentes por construção: desde o ADR 0021 o cartão
    # é pessoal e nasce na moeda de relatório do dono, enquanto o lançamento é
    # convertido para a base do workspace onde foi feito. Enquanto existia um
    # valor só, as duas leituras disputavam a mesma coluna e a fatura perdia:
    # `compute_statement_total` filtrava `currency == card.currency`, não achava
    # nada, e um cartão em USD num workspace em BRL somava R$ 0,00 com a compra
    # listada na tela. O limite nunca era consumido e o fechamento CONGELAVA o
    # zero — o erro virava histórico.
    statement_amount: Optional[Decimal] = Field(default=None, decimal_places=2, max_digits=20)
    statement_currency: Optional[str] = Field(default=None)
    statement_exchange_rate: Optional[Decimal] = Field(
        default=None, decimal_places=6, max_digits=20
    )

    # QUANDO O DINHEIRO SAIU DE FATO (ADR 0029). `None` = ainda não saiu.
    #
    # Ortogonal ao `status`, de propósito. `status` é competência — a despesa
    # existe, entra em dívidas, relatórios e rateio no instante em que é
    # confirmada. Isto é caixa: o boleto de julho pago em 14 de agosto é gasto de
    # julho e dinheiro que saiu em agosto. Antes o caixa lia `transaction_date` e
    # afirmava que TODA despesa fora do cartão saía do bolso no momento em que era
    # registrada — a forma de pagamento não entrava na conta em lugar nenhum, e
    # `pix`, `cash`, `boleto` e `bank_transfer` eram só rótulo.
    #
    # Não é o `status = paid`: aquele estado congela a despesa inteira
    # ("Despesa paga não pode ser alterada: reabra antes"), trava que existe para
    # proteger o histórico de ACERTOS. Marcar um boleto como pago não pode
    # bloquear a correção do valor ou da divisão — são fatos diferentes.
    #
    # Quem decide o valor inicial é `app.domain.settlement.resolve_settled_at`,
    # ponto único chamado por todos os caminhos de criação.
    settled_at: Optional[datetime] = None

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
    __table_args__ = (
        # Saldo por conta (ADR 0034): a varredura é "os pagamentos DESTA conta", e
        # ela roda sobre o histórico inteiro, não sobre um mês. Parcial e composto
        # porque a esmagadora maioria das linhas tem `account_id` nulo — o índice
        # cheio de coluna única que existia aqui era lido quase todo para nada.
        #
        # Sem data: ela mora em `Transaction.settled_at`, não no pagador. É a única
        # fonte em que o corte "desde o saldo inicial" não cabe no índice.
        Index(
            "ix_transactionpayer_conta",
            "account_id",
            "transaction_id",
            sqlite_where=text("account_id IS NOT NULL"),
            postgresql_where=text("account_id IS NOT NULL"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    transaction_id: int = Field(foreign_key="transaction.id", index=True)
    # Indexado pelo predicado de envolvimento (ADR 0018)
    user_id: int = Field(foreign_key="user.id", index=True)
    amount: Decimal = Field(decimal_places=2, max_digits=20)
    payment_method: Optional[PaymentMethod] = Field(default=None)
    account_id: Optional[int] = Field(default=None, foreign_key="paymentaccount.id")

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
    # `month_key_local` (ver `api/routes/transactions.py`).
    if not target.billing_month and target.transaction_date is not None:
        target.billing_month = target.transaction_date.strftime("%Y-%m")
    # Perna de fatura (ADR 0024), pelo mesmo motivo do `billing_month` acima: a
    # coluna é nullable, e uma linha ligada a uma fatura sem ela sairia do total
    # — que é exatamente o defeito que a perna veio fechar. O default é a
    # IDENTIDADE (o valor contábil, na moeda em que foi gravado), o mesmo do
    # backfill da migração: correto quando cartão e workspace compartilham a
    # moeda, e honesto quando não, porque não inventa câmbio nenhum.
    #
    # Quem SABE a moeda do cartão — as rotas, via `apply_statement_leg` — grava o
    # valor convertido antes de chegar aqui, e o valor explícito continua vencendo.
    if target.statement_id is not None and target.statement_amount is None:
        target.statement_amount = target.total_amount
        target.statement_currency = target.currency
        target.statement_exchange_rate = Decimal("1")


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
