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

from app.models.transaction import TransactionStatus


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

    # --- Contas a pagar (ADR 0029) ---------------------------------------------
    #: O que ainda não virou saída de caixa: lançamento fora do cartão sem
    #: `settled_at`. Vem do MESMO `PayablesService` que desenha a tela de Contas a
    #: pagar, para o número do topo e a lista que ele abre não divergirem.
    payables_total: Decimal = Decimal("0")
    payables_count: int = 0
    #: A parte disso que já venceu — é o que a tela realça.
    payables_overdue: Decimal = Decimal("0")

    #: Quantos valores ficaram de fora por falta de cotação (ADR 0006). Nunca é
    #: silencioso: o que não converte não vira zero.
    excluded_foreign_count: int


class PayableEntry(BaseModel):
    """Uma conta a pagar: o lançamento que ainda não saiu do caixa.

    `amount` é o que EU assumi na despesa (`TransactionPayer`), não o total dela:
    num jantar rateado que eu paguei, a conta a pagar é minha e inteira, e a parte
    do outro vira acerto — outro eixo, outra tela.
    """
    transaction_id: int
    workspace_id: int
    workspace_name: str
    title: str
    #: Dia de calendário em que vence (a data do lançamento, no fuso do app).
    due_date: date
    billing_month: Optional[str] = None
    amount: Decimal
    currency: str
    #: `None` = sem cotação para a data (ADR 0006). A linha aparece assim mesmo:
    #: numa tela de obrigação, esconder o que não converteu é pior — o valor
    #: continua sendo devido.
    converted_amount: Optional[Decimal] = None
    payment_method: Optional[str] = None
    is_overdue: bool
    #: De onde a conta veio. Saber que a linha é automática muda o que se faz com
    #: ela: confirmar o pagamento, ou ir atrás de quem deveria ter pago.
    recurring_expense_id: Optional[int] = None
    installment_no: Optional[int] = None
    installments_of: Optional[int] = None
    #: Competência anterior ao mês pedido — conta arrastada de um mês fechado.
    from_past_month: bool = False


class PayablesRead(BaseModel):
    """Contas a pagar do mês (ADR 0029).

    Os totais são a partição complementar do `cash_out` de lançamentos: o que
    está aqui é exatamente o que sairá do caixa quando for pago.
    """
    currency: str
    month: str
    total: Decimal
    overdue_total: Decimal
    due_this_month_total: Decimal
    entries: List[PayableEntry]
    excluded_foreign_count: int


class SettleResult(BaseModel):
    """Marcação de pagamento em lote.

    `skipped` existe pela mesma razão de `BulkDeleteResult`: quem confirma cinco
    contas não pode ver a operação inteira falhar porque uma delas foi cancelada
    por outra pessoa entre a leitura da tela e o clique.
    """
    status: str
    updated: int
    skipped: int


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


class LedgerEntry(BaseModel):
    """Um movimento de caixa, explicado.

    A Visão global tinha bons totais e nenhuma forma de explicar cada número: o
    usuário via "saiu R$ 4.200" e o detalhamento por origem, mas não conseguia
    chegar às LINHAS. Este é o mesmo `CashFlowService` que produz os totais,
    devolvendo as linhas em vez de somá-las — o detalhe não tem como divergir do
    total porque é a mesma consulta.
    """
    #: Uma das seis fontes do ADR 0022 (`transaction`, `statement_payment`,
    #: `settlement_sent`, `settlement_received`, `financing_installment`,
    #: `income`).
    source: str
    #: `in` | `out`.
    direction: str
    #: A data EFETIVA do movimento — quando o dinheiro se moveu, não quando o
    #: compromisso foi assumido.
    occurred_on: date
    #: Valor na moeda de origem, e a moeda dela.
    amount: Decimal
    currency: str
    #: Valor na moeda de relatório. `None` = sem cotação para a data efetiva; a
    #: linha aparece assim mesmo, marcada, em vez de sumir (ADR 0006).
    converted_amount: Optional[Decimal] = None
    title: Optional[str] = None
    workspace_id: Optional[int] = None
    workspace_name: Optional[str] = None
    card_id: Optional[int] = None
    financing_id: Optional[int] = None
    counterparty_id: Optional[int] = None
    counterparty_name: Optional[str] = None
    reference_id: Optional[int] = None


class LedgerRead(BaseModel):
    """Extrato global consolidado, com filtros e paginação."""
    currency: str
    month: str
    entries: List[LedgerEntry]
    #: Total de linhas ANTES da paginação — a UI precisa saber se há mais.
    total: int
    cash_in: Decimal
    cash_out: Decimal
    net_cash: Decimal
    excluded_foreign_count: int


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


# --- Acertos entre pessoas, camada global (ADR 0027) ------------------------
#
# Espelho tipado de `/{ws}/debts`, `/{ws}/debts/monthly` e `/{ws}/settlements`,
# agrupado por casa. Aqueles três devolvem `Dict[str, Any]` por serem anteriores a
# este módulo; os de `/me/*` nascem tipados, que é o ponto do arquivo.


class DebtRow(BaseModel):
    """Uma dívida líquida entre duas pessoas, como o `DebtService` a devolve."""
    debtor_id: int
    creditor_id: int
    amount: Decimal


class PersonDebt(DebtRow):
    """`DebtRow` com os nomes já resolvidos.

    O ledger do workspace devolve só ids — a tela da casa cruza com
    `/{ws}/members` para achar o nome. A tela global não tem uma casa só de onde
    buscar membros, então o nome vem junto.
    """
    debtor_name: str
    creditor_name: str


class WorkspaceDebtGroup(BaseModel):
    """O saldo a acertar de UMA casa. Sempre na moeda-base dela."""
    workspace_id: int
    workspace_name: str
    base_currency: str
    #: Papel do usuário nesta casa; `can_write` é o mesmo gate de
    #: `require_role(member)` que o POST de acerto aplica.
    role: Optional[str] = None
    can_write: bool
    net_debts: List[PersonDebt]
    to_pay: Decimal
    to_receive: Decimal
    #: `False` = sem cotação para a moeda-base desta casa. O grupo continua na
    #: tela com os valores dele; o que ele NÃO faz é entrar nos totais.
    converted: bool


class ExcludedWorkspace(BaseModel):
    """Casa fora dos totais por falta de cotação — com o valor na moeda dela.

    O `/me/overview` devolve só um contador (`excluded_foreign_count`) e some com
    o workspace inteiro. Aqui o usuário vê QUAL casa ficou de fora e QUANTO é,
    porque "você deve R$ 0,00" para quem deve USD 100 é pior que omitir.
    """
    workspace_id: int
    workspace_name: str
    base_currency: str
    to_pay: Decimal
    to_receive: Decimal


class PersonalDebtsRead(BaseModel):
    """Com quem eu me acerto, somando todas as casas.

    Não existe "líquido": compensar dívida de uma casa com crédito de outra é o
    que o ADR 0020 proíbe — são pessoas e acordos diferentes. `to_pay` e
    `to_receive` andam lado a lado, e cada um é informativo.
    """
    currency: str
    to_pay: Decimal
    to_receive: Decimal
    by_workspace: List[WorkspaceDebtGroup]
    excluded_workspaces: List[ExcludedWorkspace]


class Person(BaseModel):
    """`{user_id, user_name}` — o formato que o componente de ledger consome."""
    user_id: int
    user_name: str


class LedgerMember(BaseModel):
    """Quanto UMA pessoa pagou e deve no mês, nesta casa."""
    user_id: int
    paid: Decimal
    owed: Decimal
    balance: Decimal


class LedgerPayer(BaseModel):
    user_id: int
    amount: Decimal


class LedgerSplit(BaseModel):
    user_id: int
    computed_amount: Decimal


class LedgerExpense(BaseModel):
    """Uma despesa do mês, com quem pagou e como foi dividida."""
    id: int
    title: str
    total_amount: Decimal
    status: TransactionStatus
    is_paid: bool
    transaction_date: datetime
    #: Parcela `n` de `m`; `None` quando a compra não é parcelada.
    installment_no: Optional[int] = None
    installments_of: Optional[int] = None
    payers: List[LedgerPayer]
    splits: List[LedgerSplit]


class LedgerSettlement(BaseModel):
    id: int
    from_user_id: int
    to_user_id: int
    amount: Decimal
    note: Optional[str] = None
    settled_at: datetime


class LedgerTotals(BaseModel):
    total: Decimal
    paid: Decimal
    open: Decimal


class WorkspaceMonthlyLedger(BaseModel):
    """O retrato do mês de UMA casa — o mesmo payload de `/{ws}/debts/monthly`.

    Campo a campo idêntico de propósito: é o que deixa o componente do frontend
    servir às duas telas sem uma segunda forma de ler o ledger.
    """
    workspace_id: int
    workspace_name: str
    role: Optional[str] = None
    can_write: bool
    month: str
    base_currency: str
    members: List[LedgerMember]
    #: Sem nome nas linhas: aqui os nomes vêm todos de uma vez em `people`, que a
    #: tela já precisa para desenhar pagadores e divisões das despesas.
    net_debts: List[DebtRow]
    expenses: List[LedgerExpense]
    settled_total: Decimal
    settlements: List[LedgerSettlement]
    totals: LedgerTotals
    #: Nomes de todo mundo citado no ledger desta casa.
    people: List[Person]


class PersonalMonthlyDebtsRead(BaseModel):
    """O mês a acertar, uma seção por casa.

    Sem campo de moeda: cada seção tem a `base_currency` dela e não há total
    agregado. Um `currency` no topo diria que os números estão numa moeda em que
    eles não estão.
    """
    month: str
    by_workspace: List[WorkspaceMonthlyLedger]


class MonthBalance(BaseModel):
    """O quanto UM mês contribui para o saldo acumulado de quem pediu."""
    month: str
    #: Com sinal, do ponto de vista de quem pediu: negativo = devo. Já inclui os
    #: acertos marcados com este `billing_month`, por isso o mês quitado some da
    #: lista em vez de aparecer zerado.
    balance: Decimal
    #: O pareamento DAQUELE mês (recortado pelo ADR 0018), para a linha poder
    #: dizer "a quem" sem uma segunda chamada.
    net_debts: List[DebtRow]
    #: Quanto já foi acertado neste mês contando só o que me envolve.
    settled: Decimal


class OlderMonths(BaseModel):
    """Os meses além do teto da lista, somados em vez de descartados.

    Existe para a conta continuar fechando quando o histórico é longo: truncar em
    silêncio devolveria um total que não bate com as linhas exibidas.
    """
    count: int
    balance: Decimal


class DebtsByMonthRead(BaseModel):
    """De quais meses vem o saldo acumulado de quem pediu, nesta casa.

    A ponte entre `/debts` ("quanto") e `/debts/monthly` ("como foi agosto"), e a
    resposta para quem lê o saldo acumulado achando que precisa quitá-lo dentro
    do mês corrente. A conta fecha, e é isso que a tela mostra:

        balance == Σ months[].balance + older.balance + unassigned
    """
    base_currency: str
    #: O mesmo saldo que `/debts` implica para quem pediu — negativo = devo.
    balance: Decimal
    months: List[MonthBalance]
    older: OlderMonths
    #: O que não tem mês: acerto global (registrado a partir do acumulado, sem
    #: `billing_month`) e linha legada anterior ao preenchimento automático.
    unassigned: Decimal


class WorkspaceMonthsGroup(DebtsByMonthRead):
    """A origem do saldo de UMA casa, na camada global."""
    workspace_id: int
    workspace_name: str


class PersonalDebtsByMonthRead(BaseModel):
    """A origem do saldo, uma seção por casa.

    Sem total agregado, pelo mesmo motivo de `PersonalMonthlyDebtsRead`: cada
    casa vive na moeda-base dela e somar sem destino declarado é o que o ADR 0006
    proíbe. Nem haveria o que somar — o ADR 0020 já impede compensar saldo de uma
    casa com o de outra.
    """
    by_workspace: List[WorkspaceMonthsGroup]


class PersonalSettlementEntry(BaseModel):
    """Um acerto do histórico global, visto do ponto de vista de quem pediu."""
    id: int
    workspace_id: int
    workspace_name: str
    #: `Settlement` não tem coluna de moeda: o valor é da moeda-base da casa.
    currency: str
    from_user_id: int
    to_user_id: int
    counterparty_id: int
    counterparty_name: str
    #: `sent` = eu paguei; `received` = eu recebi. Na tela da casa o eixo são os
    #: nomes; aqui o eixo sou sempre eu.
    direction: str
    amount: Decimal
    note: Optional[str] = None
    billing_month: Optional[str] = None
    settled_at: datetime
    created_by_user_id: Optional[int] = None


class PersonalSettlementsRead(BaseModel):
    items: List[PersonalSettlementEntry]
    #: Total ANTES da paginação — a tela precisa saber que truncou.
    total: int
    limit: int
    offset: int


class ReportCurrencyRead(BaseModel):
    """Moeda em que os números PESSOAIS da pessoa são expressos (ADR 0019).

    Existe porque o que é da pessoa não tem workspace de onde herdar a
    moeda-base, e a visão global soma workspaces que podem ter bases diferentes
    — somar sem uma moeda de destino declarada é o que o ADR 0006 proíbe.
    """
    report_currency: str
