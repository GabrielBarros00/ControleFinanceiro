import * as React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Loader2, Lock, LockOpen, CheckCircle2 } from 'lucide-react';
import { useCardStatements, useStatementDetail, useStatementActions } from '@/hooks/use-credit-cards';
import { usePaymentAccounts } from '@/hooks/use-payment-accounts';
import { getApiErrorMessage } from '@/lib/api-error';
import { formatCurrency } from '@/lib/money';

const STATUS_LABELS: Record<string, { label: string; className: string }> = {
  open: { label: 'ABERTA', className: 'bg-emerald-500/20 text-emerald-500' },
  closed: { label: 'FECHADA', className: 'bg-amber-500/20 text-amber-500' },
  paid: { label: 'PAGA', className: 'bg-primary/20 text-primary' },
  overdue: { label: 'VENCIDA', className: 'bg-destructive/20 text-destructive' },
};

export function StatementView({ cardId }: { cardId: number | null }) {
  const { statements, isLoading } = useCardStatements(cardId);
  const [selectedStatementId, setSelectedStatementId] = React.useState<number | null>(null);

  // Seleciona a fatura mais recente por padrão
  React.useEffect(() => {
    if (statements.length > 0) {
      setSelectedStatementId((current) =>
        statements.some((s) => s.id === current) ? current : statements[0].id
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
              {statement ? `Fatura de ${statement.month}` : 'Fatura'}
            </CardTitle>
            {statement && (
              <p className="text-sm text-muted-foreground mt-1">
                Fechamento em {new Date(statement.closing_date).toLocaleDateString('pt-BR')} • Vencimento em {new Date(statement.due_date).toLocaleDateString('pt-BR')}
              </p>
            )}
          </div>
          <div className="flex items-center gap-3">
            {statements.length > 1 && (
              <select
                value={selectedStatementId ?? ''}
                onChange={(e) => setSelectedStatementId(Number(e.target.value))}
                className="h-9 rounded-md border border-border bg-background px-3 text-sm font-semibold text-foreground"
              >
                {statements.map((s) => (
                  <option key={s.id} value={s.id}>{s.month}</option>
                ))}
              </select>
            )}
            <Badge className={`${status.className} hover:opacity-90 border-none px-4 py-1`}>{status.label}</Badge>
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
                ) : statement.transactions.map((tx: { id: number; title: string; transaction_date: string; total_amount: string }) => (
                  <TableRow key={tx.id} className="border-border hover:bg-accent/30 transition-colors">
                    <TableCell className="font-medium">
                      {new Date(tx.transaction_date).toLocaleDateString('pt-BR')}
                    </TableCell>
                    <TableCell>{tx.title}</TableCell>
                    <TableCell className="text-right font-bold">
                      {formatCurrency(parseFloat(tx.total_amount))}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>

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
