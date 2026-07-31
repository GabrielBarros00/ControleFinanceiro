"""Contrato tipado da visão global (`/me/*`).

Estas rotas devolviam `Dict[str, Any]`, e o custo apareceu na auditoria: sem
`response_model` de verdade, o OpenAPI diz só "objeto", o `api.gen.ts` não ganha
tipo nenhum e o frontend escreve a interface à mão. Quando o backend muda um
campo, nada acusa — foi assim que a confirmação da troca de moeda-base passou a
imprimir `undefined` três vezes numa operação destrutiva, com o TypeScript verde
e o CI verde.

Tipo declarado aqui = tipo gerado no frontend = erro de compilação quando divergir.
Esse é o ponto do módulo.

**Decimal, não float.** Os valores saem como string no JSON (Pydantic serializa
`Decimal` assim), e o frontend já lê `string | number` em todo o app — float aqui
reintroduziria a perda de centavos que o ADR 0001 fechou.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel


class WorkspaceSlice(BaseModel):
    """A parte de UM workspace no mês da pessoa."""
    workspace_id: int
    workspace_name: str
    base_currency: str
    consumption: Decimal
    #: O que assumi nas despesas desta casa. Já se chamou `cash_out`, e não era
    #: caixa (ADR 0022) — mas é o número que fecha o acerto, que é sobre quem
    #: assumiu o quê e não sobre quando o dinheiro saiu.
    paid_in_transactions: Decimal
    to_pay: Decimal
    to_receive: Decimal


class CashOutBreakdown(BaseModel):
    """De onde veio a saída de caixa — sem isto o total não é auditável."""
    transactions: Decimal
    statement_payments: Decimal
    settlements_sent: Decimal
    financing_installments: Decimal


class CashInBreakdown(BaseModel):
    income: Decimal
    settlements_received: Decimal


class OverviewRead(BaseModel):
    """O mês da pessoa somando todos os workspaces (ADR 0020 + 0022)."""
    month: str
    currency: str

    # --- Competência: de quem é o gasto ---------------------------------------
    income: Decimal
    consumption: Decimal
    paid_in_transactions: Decimal
    #: renda − consumo. Não é saldo bancário e nunca foi.
    result: Decimal

    # --- Caixa: quando o dinheiro se moveu ------------------------------------
    #: Global, sem recorte por workspace: pagamento de fatura e parcela de
    #: financiamento não moram em workspace nenhum (ADR 0021).
    cash_in: Decimal
    cash_out: Decimal
    net_cash: Decimal
    cash_out_breakdown: CashOutBreakdown
    cash_in_breakdown: CashInBreakdown

    # --- Acerto entre pessoas --------------------------------------------------
    to_pay: Decimal
    to_receive: Decimal
    by_workspace: List[WorkspaceSlice]

    #: Quantos valores ficaram de fora por falta de cotação (ADR 0006). Nunca é
    #: silencioso: o que não converte não vira zero.
    excluded_foreign_count: int


class CommitmentStatement(BaseModel):
    card_id: int
    card_name: str
    statement_id: int
    month: str
    due_date: datetime
    amount: Decimal
    is_overdue: bool


class CommitmentFinancing(BaseModel):
    financing_id: int
    title: str
    outstanding: Decimal
    next_due_date: date
    remaining_installments: int


class CommitmentInstallment(BaseModel):
    financing_id: int
    title: str
    installment_number: int
    due_date: date
    amount: Decimal


class CommitmentsRead(BaseModel):
    """Compromissos separados por PRAZO (ADR 0021).

    O "Total a pagar" antigo somava a próxima fatura com o principal inteiro de
    cada financiamento — juntava o que vence em cinco dias com o que vence em
    quinze anos e não respondia a nenhuma das duas perguntas.
    """
    currency: str
    overdue: Decimal
    due_this_month: Decimal
    outstanding_total: Decimal
    monthly_commitment: Decimal
    cards: List[CommitmentStatement]
    financings: List[CommitmentFinancing]
    next_installments: List[CommitmentInstallment]
    excluded_foreign_count: int


class ActivityRead(BaseModel):
    """Lançamento recente em que a pessoa está envolvida, em qualquer workspace."""
    id: int
    workspace_id: int
    workspace_name: str
    title: str
    total_amount: Decimal
    #: A parte DELA no lançamento. A lista mostrava `total_amount`, o valor cheio
    #: da despesa — numa tela chamada "Onde você está envolvido", que é sobre a
    #: participação e não sobre o total da casa.
    my_share: Optional[Decimal]
    currency: str
    transaction_date: datetime
    status: str


class MonthPoint(BaseModel):
    """Um mês na série pessoal."""
    month: str
    income: Decimal
    consumption: Decimal
    result: Decimal
    cash_in: Decimal
    cash_out: Decimal
    net_cash: Decimal


class SeriesTotals(BaseModel):
    income: Decimal
    consumption: Decimal
    result: Decimal
    cash_in: Decimal
    cash_out: Decimal
    net_cash: Decimal


class WorkspaceShare(BaseModel):
    """Quanto do consumo da pessoa foi para cada casa, no período."""
    workspace_id: int
    workspace_name: str
    consumption: Decimal


class SeriesRead(BaseModel):
    """Relatório GLOBAL e pessoal: vários meses somando todos os workspaces.

    Os Relatórios do app sempre foram de um workspace — respondem "quanto esta
    casa gastou". Faltava o outro eixo: renda × consumo, resultado mês a mês e a
    participação de cada casa no meu período. Depois do ADR 0021, que tirou renda
    do workspace, os Relatórios locais nem podem mais responder isso.
    """
    currency: str
    months: List[MonthPoint]
    totals: SeriesTotals
    by_workspace: List[WorkspaceShare]
    excluded_foreign_count: int
