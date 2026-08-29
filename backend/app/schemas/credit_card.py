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


class CardNextDueRead(BaseModel):
    """A fatura que pede ATENÇÃO num cartão: a não paga mais antiga com valor.

    Viaja junto do cartão para a lista poder avisar "fechada", "vence em N dias"
    ou "vencida" sem carregar as faturas de cada um.
    """
    statement_id: int
    month: str
    status: StatementStatus
    closing_date: datetime
    due_date: datetime
    amount: Decimal
    is_overdue: bool


class CreditCardRead(BaseModel):
    """Cartão de UMA pessoa (ADR 0021) com o que a tela precisa saber dele.

    Não tem `workspace_id`, e a ausência é a regra de privacidade: nenhuma
    consulta escopada por workspace alcança este recurso.
    """
    id: int
    name: str
    limit: Decimal
    closing_day: int
    due_day: int
    currency: str
    owner_user_id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    #: Soma do que ainda pesa no limite (faturas em aberto + saldo não pago).
    committed_amount: Decimal
    #: `limit − committed_amount`.
    available_limit: Decimal
    next_due: Optional[CardNextDueRead] = None


class StatementShiftOptionRead(BaseModel):
    """Uma fatura para a qual a compra PODE ser movida (ADR 0032).

    O `shift` viaja junto com o mês exatamente para o cliente não precisar
    calculá-lo: quem escolhe "Setembro" devolve o `shift` que veio na opção, e a
    aritmética de ciclo continua inteira no servidor. É o que mantém a promessa
    do ADR 0002 (o cliente nunca aponta uma fatura) enquanto lhe dá controle
    sobre o destino.
    """
    shift: int
    month: str
    closing_date: datetime
    due_date: datetime
    exists: bool
    #: `False` = fechada ou paga; a opção aparece, desabilitada e com o motivo.
    #: Escondê-la deixaria a tela sem explicação para a fatura que o usuário
    #: procura e não acha — e é o caso frequente, porque a divergência costuma
    #: ser descoberta quando a fatura real chega, com o ciclo já fechado.
    available: bool
    status: Optional[StatementStatus] = None


class StatementTargetRead(BaseModel):
    """Em qual fatura cairia uma compra neste dia (ADR 0002) — somente leitura.

    A regra não é óbvia e por isso é anunciada: a partir do dia de fechamento a
    compra vai para o mês seguinte, e se essa fatura já estiver fechada/paga ela
    ROLA para frente. `rolled_forward` marca exatamente esse caso, que é o que
    surpreende quem digita.
    """
    month: str
    closing_date: datetime
    due_date: datetime
    #: `False` = a fatura ainda não existe (nasce no primeiro lançamento). Este
    #: preview NÃO a cria: digitar no formulário criaria faturas vazias.
    exists: bool
    #: Rolou por a fatura pedida estar fechada — NUNCA por deslocamento
    #: declarado. Medir contra o alvo natural marcaria todo `shift != 0` como
    #: rolagem, e a tela avisaria "a fatura do mês já está fechada" sobre uma
    #: compra que o próprio usuário mandou para frente.
    rolled_forward: bool
    #: O deslocamento em vigor nesta consulta (ADR 0032).
    shift: int = 0
    #: Dias entre a compra e o fechamento da fatura de destino. `None` quando a
    #: pergunta não faz sentido — destino deslocado ou rolado, ou compra já
    #: depois do fechamento. Sustenta o aviso da janela de fechamento: perto do
    #: fechamento, a chance de o emissor processar a compra já no ciclo seguinte
    #: é real, e este é o único momento em que dá para avisar ANTES do fato.
    days_to_closing: Optional[int] = None
    options: List[StatementShiftOptionRead] = []
