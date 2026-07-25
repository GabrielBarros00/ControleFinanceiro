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
import { Loader2, Lock, LockOpen, CheckCircle2, ChevronLeft, ChevronRight } from 'lucide-react';
import { useCardStatements, useStatementDetail, useStatementActions } from '@/hooks/use-credit-cards';
import { usePaymentAccounts } from '@/hooks/use-payment-accounts';
import { getApiErrorMessage } from '@/lib/api-error';
import { formatCurrency } from '@/lib/money';
import { useTxDetailStore } from '@/stores';
import { parseApiDate } from '@/lib/date';

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

interface StatementTx {
  id: number;
  title: string;
  transaction_date: string;
  total_amount: string;
  original_currency?: string | null;
  original_amount?: string | null;
  exchange_rate?: string | null;
  iof_rate?: string | null;
}

// IOF em BRL de uma compra estrangeira = valor original × câmbio × alíquota.
function iofBrl(tx: StatementTx): number {
  if (!tx.original_amount || !tx.exchange_rate || !tx.iof_rate) return 0;
  return parseFloat(tx.original_amount) * parseFloat(tx.exchange_rate) * parseFloat(tx.iof_rate);
}

export function StatementView({ cardId }: { cardId: number | null }) {
  const { statements, isLoading } = useCardStatements(cardId);
  const openDetail = useTxDetailStore((s) => s.open);
  const [selectedStatementId, setSelectedStatementId] = React.useState<number | null>(null);

  // Abre na fatura ATUAL (o ciclo aberto de hoje), não na mais recente da lista:
  // uma compra com data futura cria uma fatura à frente e roubava a seleção.
  React.useEffect(() => {
    if (statements.length > 0) {
      const fallback = statements.find((s) => s.is_current) ?? statements[0];
      setSelectedStatementId((current) =>
        statements.some((s) => s.id === current) ? current : fallback.id
      );
    } else {
      setSelectedStatementId(null);
    }
  }, [statements]);

  const { statement, isLoading: detailLoading } = useStatementDetail(cardId, selectedStatementId);
  const { close, pay, reopen, isPending } = useStatementActions(cardId);
  const { activeAccounts } = usePaymentAccounts();

  const [payOpen, setPayOpen] = React.useState(false);
  const [payAccountId, setPayAccountId] = React.useState<number | null>(null);
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

  const handlePay = async () => {
    if (!statement) return;
    setActionError(null);
    try {
      await pay({ statementId: statement.id, account_id: payAccountId });
      setPayOpen(false);
      setPayAccountId(null);
    } catch (err) {
      setActionError(getApiErrorMessage(err, 'Erro ao registrar o pagamento da fatura.'));
    }
  };

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
                Fechamento em {parseApiDate(statement.closing_date).toLocaleDateString('pt-BR')} • Vencimento em {parseApiDate(statement.due_date).toLocaleDateString('pt-BR')}
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
                ) : statement.transactions.map((tx: StatementTx) => (
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
                      </div>
                    </TableCell>
                    <TableCell className="text-right">
                      <MoneyText value={tx.total_amount} kind="expense" className="font-semibold" />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>

            {(() => {
              const iofTotal = statement.transactions.reduce((a: number, tx: StatementTx) => a + iofBrl(tx), 0);
              return iofTotal > 0 ? (
                <div className="mt-3 flex justify-end text-xs text-muted-foreground">
                  IOF total da fatura:{' '}
                  <span className="ml-1 font-semibold text-foreground">{formatCurrency(iofTotal)}</span>
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
                      onClick={() => { setPayAccountId(null); setActionError(null); setPayOpen(true); }}
                      className="gap-2 bg-primary hover:bg-primary/90 text-primary-foreground font-bold"
                    >
                      <CheckCircle2 className="h-4 w-4" /> Pagar fatura
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      disabled={isPending}
                      onClick={() => runAction(() => reopen(statement.id), 'Erro ao reabrir a fatura.')}
                      className="gap-2"
                    >
                      <LockOpen className="h-4 w-4" /> Reabrir
                    </Button>
                  </>
                )}
                {statement.status === 'paid' && (
                  <Button
                    type="button"
                    variant="ghost"
                    disabled={isPending}
                    onClick={() => runAction(() => reopen(statement.id), 'Erro ao estornar o pagamento.')}
                    className="gap-2"
                  >
                    <LockOpen className="h-4 w-4" /> Reabrir (estornar pagamento)
                  </Button>
                )}
              </div>

              <div className="bg-accent/40 p-6 rounded-xl border border-border min-w-[300px]">
                <div className="flex justify-between text-lg font-bold">
                  <span>Total da Fatura</span>
                  <span className="text-primary">{formatCurrency(parseFloat(statement.computed_total))}</span>
                </div>
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
            <DialogTitle>Pagar fatura</DialogTitle>
            <DialogDescription>
              Registre de qual conta saiu o pagamento. O valor pago é o total fechado da fatura.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
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
                Total a pagar: <span className="font-bold text-foreground">{formatCurrency(parseFloat(statement.computed_total))}</span>
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
