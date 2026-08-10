import * as React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";
import { MoneyText } from "@/components/money/MoneyText";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { MoneyInput } from "@/components/ui/MoneyInput";
import { Loader2, Lock, LockOpen, CheckCircle2, ChevronLeft, ChevronRight, AlertTriangle, Clock, Info } from 'lucide-react';
import { cn } from '@/lib/utils';
import { statementAlert, type StatementAlert } from '@/lib/statement-alert';
import {
  useCardStatements, useCreditCards, useStatementDetail, useStatementActions,
  type CreditCardSummary, type StatementTransaction,
} from '@/hooks/use-credit-cards';
import { usePaymentAccounts } from '@/hooks/use-payment-accounts';
import { getApiErrorMessage } from '@/lib/api-error';
import { currencySymbol, formatCurrency } from '@/lib/money';
import { useConfirm } from '@/components/ui/confirm';
import { useTxDetailStore } from '@/stores';
import { parseApiDate, parseApiDay } from '@/lib/date';

const ALERTA_POR_TOM: Record<
  StatementAlert['tone'],
  { box: string; icone: string; icon: typeof AlertTriangle }
> = {
  danger: { box: 'border-destructive/30 bg-destructive/10', icone: 'text-destructive', icon: AlertTriangle },
  warning: { box: 'border-warning/30 bg-warning-subtle', icone: 'text-warning', icon: Clock },
  info: { box: 'border-border bg-muted/50', icone: 'text-muted-foreground', icon: Info },
  success: { box: 'border-emerald-500/30 bg-emerald-500/10', icone: 'text-emerald-500', icon: CheckCircle2 },
};

const STATUS_LABELS: Record<string, { label: string; tone: PillTone }> = {
  open: { label: 'Aberta', tone: 'success' },
  closed: { label: 'Fechada', tone: 'warning' },
  paid: { label: 'Paga', tone: 'brand' },
  overdue: { label: 'Vencida', tone: 'danger' },
};

// "2026-07" -> "Julho de 2026" — mesmo rótulo do PeriodPicker do resto do site.
function statementMonthLabel(month: string): string {
  const [y, m] = month.split('-').map(Number);
  const s = new Date(y, m - 1, 1).toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' });
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// IOF em BRL de uma compra estrangeira = valor original × câmbio × alíquota.
function iofBrl(tx: StatementTransaction): number {
  if (!tx.original_amount || !tx.exchange_rate || !tx.iof_rate) return 0;
  return parseFloat(tx.original_amount) * parseFloat(tx.exchange_rate) * parseFloat(tx.iof_rate);
}

export function StatementView({ cardId }: { cardId: number | null }) {
  const { statements, isLoading } = useCardStatements(cardId);
  const openDetail = useTxDetailStore((s) => s.open);
  const [selectedStatementId, setSelectedStatementId] = React.useState<number | null>(null);

  // Abre na fatura QUE PEDE ATENÇÃO: a não paga mais antiga com valor — a de
  // vencimento mais próximo, a que corre risco de atraso. Quando ela é quitada,
  // a próxima pendente (ou o ciclo corrente) assume sozinha, que é o
  // comportamento "pagou → mostra o mês seguinte".
  //
  // Antes abria sempre no ciclo corrente, e no dia do fechamento isso era uma
  // fatura VAZIA enquanto as compras do mês estavam na anterior, ainda a pagar.
  // A lista vem em month.desc(), então a mais antiga é a última.
  React.useEffect(() => {
    if (statements.length === 0) {
      setSelectedStatementId(null);
      return;
    }
    const pendentes = statements.filter(
      (s) => s.status !== 'paid' && parseFloat(s.computed_total) > 0
    );
    const alvo =
      pendentes[pendentes.length - 1] ??
      statements.find((s) => s.is_current) ??
      statements[0];
    setSelectedStatementId((current) =>
      statements.some((s) => s.id === current) ? current : alvo.id
    );
  }, [statements]);

  // Só busca o detalhe de uma fatura que PERTENCE ao cartão atual. Ao trocar de
  // cartão, `selectedStatementId` continua com o id do cartão anterior por um
  // render (a lista nova ainda está carregando e o efeito acima só corre
  // depois) — e a tela disparava GET /cards/2/statements/1 → 404, sem faixa de
  // alerta e sem botões do ciclo.
  const statementOfThisCard = statements.some((s) => s.id === selectedStatementId)
    ? selectedStatementId
    : null;
  const { statement, isLoading: detailLoading } = useStatementDetail(cardId, statementOfThisCard);
  const { close, pay, reopen, isPending } = useStatementActions(cardId);
  const { activeAccounts } = usePaymentAccounts();
  // A fatura é denominada na moeda DO CARTÃO (é assim que
  // `compute_statement_total` a calcula, ADR 0021) — não na moeda-base do
  // workspace aberto. Com `useBaseCurrency`, um cartão em USD tinha total,
  // saldo, IOF e cada linha da fatura rotulados em R$ porque o último workspace
  // visitado era brasileiro: os números certos com o símbolo errado, que é a
  // forma mais convincente de mentir.
  const { cards } = useCreditCards();
  const cardCurrency =
    (cards as CreditCardSummary[]).find((c) => c.id === cardId)?.currency ?? 'BRL';
  const confirm = useConfirm();

  const [payOpen, setPayOpen] = React.useState(false);
  const [payAccountId, setPayAccountId] = React.useState<number | null>(null);
  const [payAmount, setPayAmount] = React.useState<number | undefined>(undefined);
  const [actionError, setActionError] = React.useState<string | null>(null);

  if (!cardId) {
    return (
      <Card className="bg-card border-border p-12 text-center">
        <p className="text-muted-foreground">Selecione um cartão acima para ver as faturas.</p>
      </Card>
    );
  }

  if (isLoading) {
    return (
      <div className="h-[200px] flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (statements.length === 0) {
    return (
      <Card className="bg-card border-border p-12 text-center">
        <p className="text-muted-foreground">
          Este cartão ainda não tem faturas. Lance uma transação vinculada ao cartão para gerar a primeira.
        </p>
      </Card>
    );
  }

  // Faturas são discretas (nem todo mês tem uma) — o stepper anda pela LISTA de
  // faturas, não por meses de calendário como o PeriodPicker; statements[0] é a
  // mais recente. Anterior = mais antiga (índice+1); próxima = mais nova (−1).
  const statementIndex = statements.findIndex((s) => s.id === selectedStatementId);

  // Vencida sobrepõe o rótulo de aberta/fechada
  const statusKey = statement
    ? statement.is_overdue && statement.status !== 'paid'
      ? 'overdue'
      : statement.status
    : 'open';
  const status = STATUS_LABELS[statusKey] ?? STATUS_LABELS.open;

  const runAction = async (fn: () => Promise<unknown>, fallback: string) => {
    setActionError(null);
    try {
      await fn();
    } catch (err) {
      setActionError(getApiErrorMessage(err, fallback));
    }
  };

  // Saldo pendente: a fatura aceita pagamentos parciais e só vira "paga" quando
  // chega a zero, então o número que importa nos botões e no diálogo é este —
  // não o total da fatura.
  const paidSoFar = statement ? parseFloat(statement.paid_amount) : 0;
  const remaining = statement ? parseFloat(statement.remaining_amount) : 0;
  // O critério é o SALDO, não o status. Nos estados normais dá no mesmo (fatura
  // `paid` tem saldo zero), mas existe um estado contraditório — `paid` com saldo
  // devedor, que o backfill de moeda estrangeira já produziu — e com o teste no
  // status ele aparecia como quitado: o bloco abaixo sumia e a tela mostrava só
  // "Total da Fatura", sem dizer que parte dele ainda não foi paga.
  const partiallyPaid = paidSoFar > 0 && remaining > 0;

  const openPayDialog = () => {
    setPayAccountId(null);
    setPayAmount(remaining);
    setActionError(null);
    setPayOpen(true);
  };

  /**
   * Reabrir ESTORNA todos os pagamentos da fatura (`reopen_statement`), e com
   * saldo cumulativo uma fatura ainda "fechada" já pode ter pagamentos parciais.
   * O botão dela dizia só "Reabrir", a ação era imediata, e um clique tirava
   * dinheiro do caixa e mexia no limite disponível sem nenhum aviso — enquanto o
   * botão da fatura PAGA já avisava "estornar pagamento". Confirmação só quando
   * há o que estornar: pedi-la para uma fatura sem pagamento seria ruído.
   */
  const handleReopen = async () => {
    if (!statement) return;
    if (paidSoFar > 0) {
      const ok = await confirm({
        title: 'Reabrir e estornar os pagamentos?',
        // O sentido do caixa estava INVERTIDO aqui. `reopen` faz soft delete dos
        // `StatementPayment` (credit_card_service), e é o pagamento de fatura que
        // constitui a saída de caixa (ADR 0022) — estorná-lo devolve o dinheiro
        // ao mês, não o faz sair de novo. Só o limite volta a ficar preso.
        description:
          `Esta fatura já tem ${formatCurrency(paidSoFar, cardCurrency)} pago. ` +
          'Reabrir estorna esse valor: ele volta para o seu caixa do mês e o ' +
          'limite do cartão volta a ficar comprometido.',
        confirmLabel: 'Reabrir e estornar',
        destructive: true,
      });
      if (!ok) return;
    }
    await runAction(() => reopen(statement.id), 'Erro ao reabrir a fatura.');
  };

  const handlePay = async () => {
    if (!statement) return;
    setActionError(null);
    try {
      await pay({ statementId: statement.id, account_id: payAccountId, amount: payAmount });
      setPayOpen(false);
      setPayAccountId(null);
      // Só avança quando o pagamento QUITA a fatura: num pagamento parcial ela
      // continua fechada e com saldo, e pular para o mês seguinte esconderia
      // justamente o que ainda falta pagar.
      const quitou = payAmount === undefined || payAmount >= remaining;
      if (quitou && statementIndex > 0) {
        setSelectedStatementId(statements[statementIndex - 1].id);
      }
    } catch (err) {
      setActionError(getApiErrorMessage(err, 'Erro ao registrar o pagamento da fatura.'));
    }
  };

  // Aviso da fatura selecionada — mesma regra do selo no cartão
  const alert = statement
    ? statementAlert(
        {
          status: statement.status,
          due_date: statement.due_date,
          closing_date: statement.closing_date,
          amount: parseFloat(statement.computed_total),
          is_overdue: statement.is_overdue,
        },
        cardCurrency,
      )
    : null;

  return (
    <Card className="bg-card border-border">
      <CardHeader>
        <div className="flex justify-between items-center flex-wrap gap-3">
          <div>
            <CardTitle className="text-xl">
              {statement ? `Fatura de ${statementMonthLabel(statement.month)}` : 'Fatura'}
            </CardTitle>
            {statement && (
              <p className="text-sm text-muted-foreground mt-1">
                Fechamento em {parseApiDay(statement.closing_date).toLocaleDateString('pt-BR')} • Vencimento em {parseApiDay(statement.due_date).toLocaleDateString('pt-BR')}
              </p>
            )}
          </div>
          <div className="flex items-center gap-3">
            {statements.length > 1 && statementIndex >= 0 && (
              <div className="inline-flex items-center rounded-lg border border-border bg-background">
                <button
                  type="button"
                  aria-label="Fatura anterior"
                  disabled={statementIndex >= statements.length - 1}
                  onClick={() => setSelectedStatementId(statements[statementIndex + 1].id)}
                  className="rounded-l-lg p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <span className="min-w-[132px] select-none text-center text-sm font-medium text-foreground">
                  {statementMonthLabel(statements[statementIndex].month)}
                </span>
                <button
                  type="button"
                  aria-label="Próxima fatura"
                  disabled={statementIndex <= 0}
                  onClick={() => setSelectedStatementId(statements[statementIndex - 1].id)}
                  className="rounded-r-lg p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            )}
            <StatusPill tone={status.tone}>{status.label}</StatusPill>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {detailLoading || !statement ? (
          <div className="h-[120px] flex items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
          </div>
        ) : (
          <>
            {alert && (
              <div
                role={alert.tone === 'danger' ? 'alert' : undefined}
                data-testid="statement-alert"
                className={cn(
                  'mb-5 flex items-start gap-2.5 rounded-xl border p-3.5 text-sm',
                  ALERTA_POR_TOM[alert.tone].box,
                )}
              >
                {React.createElement(ALERTA_POR_TOM[alert.tone].icon, {
                  className: cn('mt-0.5 h-4 w-4 shrink-0', ALERTA_POR_TOM[alert.tone].icone),
                })}
                <p>
                  <span className="font-bold text-foreground">{alert.title}.</span>{' '}
                  <span className="text-muted-foreground">{alert.detail}</span>
                </p>
              </div>
            )}

            <Table>
              <TableHeader>
                <TableRow className="border-border hover:bg-transparent">
                  <TableHead className="text-muted-foreground">Data</TableHead>
                  <TableHead className="text-muted-foreground">Estabelecimento</TableHead>
                  <TableHead className="text-muted-foreground text-right">Valor</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {statement.transactions.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={3} className="h-24 text-center text-muted-foreground">
                      Nenhuma transação nesta fatura.
                    </TableCell>
                  </TableRow>
                ) : statement.transactions.map((tx: StatementTransaction) => (
                  <TableRow
                    key={tx.id}
                    onClick={() => openDetail(tx.id)}
                    title="Ver detalhes do lançamento"
                    className="cursor-pointer border-border hover:bg-accent/30 transition-colors"
                  >
                    <TableCell className="font-medium">
                      {parseApiDate(tx.transaction_date).toLocaleDateString('pt-BR')}
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-col">
                        <span>{tx.title}</span>
                        {tx.original_currency && tx.original_amount && (
                          <span className="text-xs text-muted-foreground">
                            {formatCurrency(parseFloat(tx.original_amount), tx.original_currency)}
                            {tx.iof_rate && parseFloat(tx.iof_rate) > 0 &&
                              ` · IOF ${(parseFloat(tx.iof_rate) * 100).toLocaleString('pt-BR', { maximumFractionDigits: 2 })}%`}
                          </span>
                        )}
                        {/* Quando a compra foi lançada num workspace de outra
                            moeda, o valor contábil dela é um número diferente do
                            que a fatura cobra. Mostrar os dois é o que evita a
                            pergunta "por que R$ 100 viraram US$ 20?". */}
                        {tx.statement_currency && tx.currency !== tx.statement_currency && (
                          <span className="text-xs text-muted-foreground">
                            {formatCurrency(parseFloat(tx.total_amount), tx.currency)} no workspace
                          </span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="text-right">
                      {/* `statement_amount`/`statement_currency`: o valor DE
                          FATURA (ADR 0024). Antes esta célula desenhava
                          `total_amount` — a perna contábil, na moeda-base do
                          workspace — rotulado com a moeda do cartão, então uma
                          compra de R$ 100 num cartão em dólar aparecia como
                          US$ 100 e não entrava no total logo abaixo. */}
                      <MoneyText
                        value={tx.statement_amount ?? tx.total_amount}
                        kind="expense"
                        currency={tx.statement_currency ?? cardCurrency}
                        className="font-semibold"
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>

            {(() => {
              const iofTotal = statement.transactions.reduce((a: number, tx: StatementTransaction) => a + iofBrl(tx), 0);
              return iofTotal > 0 ? (
                <div className="mt-3 flex justify-end text-xs text-muted-foreground">
                  IOF total da fatura:{' '}
                  <span className="ml-1 font-semibold text-foreground">{formatCurrency(iofTotal, cardCurrency)}</span>
                </div>
              ) : null;
            })()}

            <div className="mt-8 flex flex-col sm:flex-row justify-between items-stretch sm:items-end gap-4">
              {/* Ciclo da fatura (ADR 0011): fechar → pagar → reabrir */}
              <div className="flex items-center gap-2">
                {statement.status === 'open' && (
                  <Button
                    type="button"
                    variant="outline"
                    disabled={isPending}
                    onClick={() => runAction(() => close(statement.id), 'Erro ao fechar a fatura.')}
                    className="gap-2"
                  >
                    <Lock className="h-4 w-4" /> Fechar fatura
                  </Button>
                )}
                {statement.status === 'closed' && (
                  <>
                    <Button
                      type="button"
                      disabled={isPending}
                      onClick={openPayDialog}
                      className="gap-2 bg-primary hover:bg-primary/90 text-primary-foreground font-bold"
                    >
                      <CheckCircle2 className="h-4 w-4" />
                      {partiallyPaid ? 'Pagar saldo restante' : 'Pagar fatura'}
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      disabled={isPending}
                      onClick={handleReopen}
                      className="gap-2"
                    >
                      {/* O rótulo já anuncia o estorno quando há o que estornar:
                          numa fatura fechada com pagamento parcial, "Reabrir"
                          sozinho escondia metade do que o botão faz. */}
                      <LockOpen className="h-4 w-4" />
                      {partiallyPaid ? 'Reabrir (estornar pagamentos)' : 'Reabrir'}
                    </Button>
                  </>
                )}
                {statement.status === 'paid' && (
                  <Button
                    type="button"
                    variant="ghost"
                    disabled={isPending}
                    onClick={handleReopen}
                    className="gap-2"
                  >
                    <LockOpen className="h-4 w-4" /> Reabrir (estornar pagamento)
                  </Button>
                )}
              </div>

              <div className="bg-accent/40 p-6 rounded-xl border border-border min-w-[300px]">
                <div className="flex justify-between text-lg font-bold">
                  <span>Total da Fatura</span>
                  <span className="text-primary">{formatCurrency(parseFloat(statement.computed_total), cardCurrency)}</span>
                </div>
                {/* Só aparece quando houve pagamento parcial: numa fatura paga
                    de uma vez, "pago" e "total" seriam a mesma linha repetida. */}
                {partiallyPaid && (
                  <div className="mt-3 space-y-1 border-t border-border pt-3 text-sm">
                    <div className="flex justify-between text-muted-foreground">
                      <span>Pago até agora</span>
                      <span>{formatCurrency(paidSoFar, cardCurrency)}</span>
                    </div>
                    <div className="flex justify-between font-semibold text-foreground">
                      <span>Saldo restante</span>
                      <span>{formatCurrency(remaining, cardCurrency)}</span>
                    </div>
                  </div>
                )}
              </div>
            </div>

            {actionError && (
              <p role="alert" className="mt-3 text-sm text-destructive font-medium text-right">{actionError}</p>
            )}
          </>
        )}
      </CardContent>

      <Dialog open={payOpen} onOpenChange={setPayOpen}>
        <DialogContent className="bg-card border-border sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{partiallyPaid ? 'Pagar saldo restante' : 'Pagar fatura'}</DialogTitle>
            <DialogDescription>
              Registre quanto foi pago e de qual conta saiu. Pagar menos que o saldo
              mantém a fatura em aberto com o restante pendente.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="pay-amount">Valor pago</Label>
              <MoneyInput
                id="pay-amount"
                value={payAmount}
                onChange={setPayAmount}
                prefix={currencySymbol(cardCurrency)}
                className="font-bold"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="pay-account">Conta de origem (opcional)</Label>
              <select
                id="pay-account"
                value={payAccountId ?? ''}
                onChange={(e) => setPayAccountId(e.target.value ? Number(e.target.value) : null)}
                className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm text-foreground"
              >
                <option value="">Sem conta específica</option>
                {activeAccounts.map((a) => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
              </select>
            </div>
            {statement && (
              <p className="text-sm text-muted-foreground">
                {partiallyPaid && (
                  <>Já pago: {formatCurrency(paidSoFar, cardCurrency)}<br /></>
                )}
                Saldo a pagar:{' '}
                <span className="font-bold text-foreground">{formatCurrency(remaining, cardCurrency)}</span>
              </p>
            )}
            {actionError && <p role="alert" className="text-xs text-destructive font-medium">{actionError}</p>}
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setPayOpen(false)}>Cancelar</Button>
            <Button type="button" onClick={handlePay} disabled={isPending} className="bg-primary font-bold px-8">
              {isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Confirmar pagamento'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
