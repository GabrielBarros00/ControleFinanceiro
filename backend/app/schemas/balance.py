"""Contrato tipado do saldo, do extrato de conta e da transferência (ADR 0034).

Tipado desde o primeiro dia pela razão registrada em `schemas/overview.py`: sem
`response_model` de verdade o OpenAPI diz só "objeto", o `api.gen.ts` não ganha
tipo e o frontend passa a escrever a interface à mão — que é como uma confirmação
destrutiva chegou a imprimir `undefined` três vezes com o CI verde.

`Decimal` sai como string no JSON (o frontend já lê `string | number` em todo o
app). Float aqui reintroduziria a perda de centavos que o ADR 0001 fechou.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.payment_account import PaymentAccountType
from app.schemas.common import DESCRIPTION_MAX, MAX_MONEY


class AccountBalanceRead(BaseModel):
    """O saldo de uma conta, com o rastro de como ele foi calculado."""

    account_id: int
    name: str
    type: PaymentAccountType
    currency: str
    active: bool
    is_default: bool
    #: `None` = a conta ainda não tem saldo inicial. A tela pede o número em vez de
    #: mostrar zero: um zero ali é um valor errado apresentado com a confiança de
    #: um certo, e a atualização não inventa saldo nenhum (§6 do pedido).
    opening_amount: Optional[Decimal] = None
    opening_on: Optional[date] = None
    balance: Optional[Decimal] = None
    #: Quantos movimentos entraram na conta desde a abertura. Exposto para um saldo
    #: errado ser diagnosticável sem abrir o banco.
    movements_counted: int = 0


class ProjectionLine(BaseModel):
    """Uma parcela da projeção, nomeada — "a pagar: 4.380" sem detalhe não é
    auditável pela pessoa, que não teria como saber se a fatura entrou ou não."""

    kind: str  # payables | statements | financing | income | overdue
    label: str
    amount: Decimal
    count: int = 0


class BalanceRead(BaseModel):
    """Saldo atual + projeção até o fim do mês (ADR 0034)."""

    #: Moeda de RELATÓRIO da pessoa. O saldo de cada conta é na moeda dela; este
    #: total é conversão de cortesia, pela cotação de hoje.
    currency: str
    #: `None` = nenhuma conta tem saldo configurado (não é "zero reais").
    total: Optional[Decimal] = None
    accounts: List[AccountBalanceRead] = []

    # --- Projeção -------------------------------------------------------------
    month: str
    #: Renda prevista ainda não recebida, com competência até o fim do mês.
    receivable_total: Decimal = Decimal("0")
    #: Contas a pagar + faturas que vencem no mês + parcelas de financiamento.
    payable_total: Decimal = Decimal("0")
    #: O que JÁ VENCEU e segue em aberto — fora da projeção de propósito.
    #:
    #: "Até o fim do mês" com doze meses de atraso embutidos não responde nem
    #: "quanto vou ter" nem "quanto eu devo". Separar não é esconder: o valor
    #: continua na resposta e ganha linha própria no `breakdown`, com a tela
    #: levando a Contas a pagar, que detalha item a item.
    overdue_total: Decimal = Decimal("0")
    #: `saldo atual + a receber − a pagar`. `None` quando não há saldo atual —
    #: projetar a partir de um saldo desconhecido daria um número inventado.
    projected_balance: Optional[Decimal] = None
    breakdown: List[ProjectionLine] = []

    # --- Sinais de que o saldo pode não fechar --------------------------------
    #: Movimentos de caixa sem conta declarada, a partir da data da abertura mais
    #: antiga. Não afetam saldo nenhum — e o contador existe para isso não ser mudo.
    unassigned_movements: int = 0
    #: Movimentos COM conta, mas anteriores à abertura dela. Também não contam (já
    #: estão dentro do saldo informado); sem este número, quem lança em janeiro o
    #: extrato de dezembro vê o saldo não se mexer e não entende por quê.
    movements_before_opening: int = 0
    accounts_without_opening: int = 0
    excluded_foreign_count: int = 0


class OpeningBalanceRequest(BaseModel):
    """"Em tal dia eu tinha tanto" — o ponto de partida contábil da conta.

    Não é renda, não é despesa e não entra em resultado de mês nenhum.
    """

    amount: Decimal = Field(le=MAX_MONEY, ge=-MAX_MONEY)
    #: Data CIVIL do saldo. É ela que define a partir de quando os movimentos
    #: passam a contar — o que veio antes já está dentro do número informado.
    as_of: date


class AdjustmentRequest(BaseModel):
    """Conciliação: "o banco mostra outro número".

    O corpo traz o saldo REAL, não a diferença — é o que a pessoa tem à mão. O
    servidor calcula o delta e grava o movimento, para os dois nunca discordarem.
    """

    real_balance: Decimal = Field(le=MAX_MONEY, ge=-MAX_MONEY)
    occurred_on: Optional[date] = None
    note: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)


class AdjustmentRead(BaseModel):
    id: int
    account_id: int
    #: A diferença calculada, com sinal. É o que vira linha no extrato.
    amount: Decimal
    occurred_on: date
    description: Optional[str] = None
    #: O saldo antes e depois, para a confirmação da tela poder dizer as duas
    #: coisas sem refazer a conta.
    previous_balance: Decimal
    new_balance: Decimal


class StatementLine(BaseModel):
    occurred_on: date
    source: str
    title: Optional[str] = None
    #: COM SINAL: positivo entrou, negativo saiu.
    amount: Decimal
    #: O saldo DEPOIS desta linha. É o que responde "por que o saldo é esse".
    #: `None` quando a conta não tem saldo inicial: uma coluna que começasse em
    #: zero afirmaria que a conta estava zerada, e ninguém disse isso.
    running_balance: Optional[Decimal] = None
    reference_id: Optional[int] = None
    workspace_id: Optional[int] = None


class AccountStatementRead(BaseModel):
    account_id: int
    account_name: str
    currency: str
    opening_amount: Optional[Decimal] = None
    opening_on: Optional[date] = None
    balance: Optional[Decimal] = None
    entries: List[StatementLine] = []


class TransferCreate(BaseModel):
    from_account_id: int
    to_account_id: int
    from_amount: Decimal = Field(gt=0, le=MAX_MONEY)
    #: Obrigatório quando as contas estão em moedas diferentes. Ausente com moedas
    #: iguais significa "o mesmo valor" — nada é convertido em silêncio.
    to_amount: Optional[Decimal] = Field(default=None, gt=0, le=MAX_MONEY)
    occurred_on: Optional[date] = None
    note: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)


class TransferRead(BaseModel):
    id: int
    from_account_id: int
    to_account_id: int
    from_account_name: str = ""
    to_account_name: str = ""
    from_amount: Decimal
    to_amount: Decimal
    #: `None` quando as duas contas estão na mesma moeda. Derivado dos dois
    #: valores, nunca informado à parte.
    exchange_rate: Optional[Decimal] = None
    occurred_at: datetime
    note: Optional[str] = None
