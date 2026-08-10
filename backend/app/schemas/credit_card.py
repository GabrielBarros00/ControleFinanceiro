"""Contrato tipado da fatura de cartão (`/me/credit-cards/.../statements`).

Mesma razão de `schemas/overview.py`: estas rotas devolviam `Dict[str, Any]`, o
OpenAPI dizia só "objeto", o `api.gen.ts` não ganhava tipo e o frontend escrevia
a interface à mão — em `StatementView.tsx` ela existe literalmente, com oito
campos copiados. Quando o backend muda um campo, nada acusa.

O gancho concreto desta onda é o pagamento parcial: `paid_amount` e
`remaining_amount` são campos NOVOS que a tela precisa ler para dizer "faltam
R$ 700". Nascer sem tipo seria repetir o defeito.

**Decimal, não float** — os valores saem como string no JSON e o frontend já lê
`string | number` em todo o app; float aqui reintroduziria a perda de centavos
que o ADR 0001 fechou.
"""
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel

from app.models.credit_card import StatementStatus


class StatementPaymentRead(BaseModel):
    """Um pagamento da fatura. São vários desde que o saldo virou cumulativo."""
    id: int
    amount: Decimal
    paid_at: datetime
    account_id: Optional[int] = None
    note: Optional[str] = None


class StatementRead(BaseModel):
    """A fatura como a tela precisa dela.

    `total_amount` é o valor CONGELADO no fechamento (zero enquanto aberta);
    `computed_total` é o total efetivo — calculado quando aberta, congelado
    depois. Os dois convivem desde o ADR 0011 e não são intercambiáveis.
    """
    id: int
    card_id: int
    month: str
    closing_date: datetime
    due_date: datetime
    status: StatementStatus
    total_amount: Decimal
    closed_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    #: Total efetivo: soma calculada enquanto aberta, congelada depois.
    computed_total: Decimal
    #: Derivado na leitura, nunca persistido (ADR 0011).
    is_overdue: bool
    #: Soma dos pagamentos vivos. Antes ninguém somava, e pagar R$ 1 de uma
    #: fatura de R$ 1.000 a marcava como quitada.
    paid_amount: Decimal
    #: `computed_total − paid_amount`, nunca negativo. É o que compromete limite
    #: e o teto do próximo pagamento.
    remaining_amount: Decimal
    payments: List[StatementPaymentRead] = []
    #: Lançamentos vivos da fatura que o total NÃO soma — só linha legada, de
    #: antes da perna de fatura existir (ADR 0024). Normalmente 0; quando não é,
    #: a tela avisa em vez de deixar um total incompleto parecer completo.
    excluded_from_total_count: int = 0


class StatementListItemRead(StatementRead):
    #: O ciclo aberto de hoje. A tela não pode deduzir isso de "a mais recente":
    #: uma compra com data futura cria uma fatura à frente que não é a atual.
    is_current: bool


class StatementTransactionRead(BaseModel):
    """A compra como ela aparece DENTRO da fatura.

    Enxuto de propósito: `TransactionRead` carrega payers/splits/items/tags, e
    tipar a lista com ele obrigaria a carregar essas relações — um N+1 por linha
    da fatura para dados que esta tela não desenha.
    """
    id: int
    title: str
    transaction_date: datetime
    total_amount: Decimal
    currency: str
    status: str
    workspace_id: int
    installment_no: Optional[int] = None
    installments_of: Optional[int] = None
    # O valor COBRADO nesta fatura, na moeda do cartão (ADR 0024). É este que a
    # linha exibe e o que o rodapé soma. `total_amount`/`currency` continuam
    # viajando porque são a perna contábil — quanto a compra pesa no orçamento do
    # workspace —, e a tela mostra os dois quando divergem.
    statement_amount: Optional[Decimal] = None
    statement_currency: Optional[str] = None
    # Conversão congelada quando a compra foi estrangeira — a tela calcula o IOF
    # em moeda-base a partir daqui (original × câmbio × alíquota).
    original_amount: Optional[Decimal] = None
    original_currency: Optional[str] = None
    exchange_rate: Optional[Decimal] = None
    iof_rate: Optional[Decimal] = None
    rate_source: Optional[str] = None


class StatementDetailRead(StatementRead):
    transactions: List[StatementTransactionRead] = []
