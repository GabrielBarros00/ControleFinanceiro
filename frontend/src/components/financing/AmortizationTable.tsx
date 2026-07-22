import * as React from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Progress } from "@/components/ui/progress";
import { StatusPill } from "@/components/ui/status-pill";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MoneyInput } from "@/components/ui/MoneyInput";
import { Loader2, Trash2 } from 'lucide-react';
import { useFinancing, useFinancingSchedule, type Financing } from '@/hooks/use-financing';
import { formatCurrency } from '@/lib/money';
import { toast } from '@/stores/toast';
import { useConfirm } from '@/components/ui/confirm';

// Base UI Select abre num portal fora do focus-trap do Dialog (Radix) e fecha
// na hora — dentro de diálogos usamos <select> nativo (mesmo padrão de
// SettlementDialog/RecurringTransactionsPage/PaymentMethodField).
const selectClass =
  'flex h-10 w-full rounded-md border border-border bg-background px-3 py-2 text-sm font-semibold text-foreground focus:outline-none focus:ring-2 focus:ring-ring';

function CreateFinancingDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { create } = useFinancing();
  const [title, setTitle] = React.useState('');
  const [totalAmount, setTotalAmount] = React.useState(0);
  const [interestRate, setInterestRate] = React.useState('1.00'); // % ao mês
  const [installments, setInstallments] = React.useState(12);
  const [method, setMethod] = React.useState<'SAC' | 'PRICE'>('SAC');
  const [startDate, setStartDate] = React.useState(() => new Date().toISOString().slice(0, 10));
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const handleCreate = async () => {
    if (!title.trim() || totalAmount <= 0 || installments < 1) {
      setError('Preencha título, valor e parcelas.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await create({
        title: title.trim(),
        total_amount: String(totalAmount),
        interest_rate: String(Number(interestRate.replace(',', '.')) / 100),
        start_date: startDate,
        installments_count: installments,
        method,
      });
      onOpenChange(false);
      setTitle(''); setTotalAmount(0); setInterestRate('1.00'); setInstallments(12);
    } catch {
      setError('Erro ao criar financiamento.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-card border-border sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>Novo Financiamento</DialogTitle>
          <DialogDescription>O cronograma de amortização é gerado automaticamente.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label>Título</Label>
            <Input placeholder="Ex: Apartamento, Carro..." value={title} onChange={(e) => setTitle(e.target.value)} className="bg-background/50" />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Valor Financiado</Label>
              <MoneyInput value={totalAmount} onChange={setTotalAmount} className="bg-background/50" />
            </div>
            <div className="space-y-2">
              <Label>Juros (% ao mês)</Label>
              <Input type="text" inputMode="decimal" value={interestRate} onChange={(e) => setInterestRate(e.target.value)} className="bg-background/50" />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-2">
              <Label>Parcelas</Label>
              <Input type="number" min={1} max={600} value={installments} onChange={(e) => setInstallments(Number(e.target.value))} className="bg-background/50" />
            </div>
            <div className="space-y-2">
              <Label>Início</Label>
              <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="bg-background/50" />
            </div>
            <div className="space-y-2">
              <Label>Sistema</Label>
              <select
                value={method}
                onChange={(e) => setMethod(e.target.value as 'SAC' | 'PRICE')}
                className={selectClass}
              >
                <option value="SAC" className="bg-card">SAC</option>
                <option value="PRICE" className="bg-card">PRICE</option>
              </select>
            </div>
          </div>
          {error && <p className="text-xs text-destructive font-medium">{error}</p>}
        </div>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Cancelar</Button>
          <Button type="button" onClick={handleCreate} disabled={saving} className="bg-primary font-bold px-8">
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Criar'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function FinancingDetail({ financing }: { financing: Financing }) {
  const { schedule, settlement } = useFinancingSchedule(financing.id);
  const { payInstallment } = useFinancing();

  const unpaid = schedule.filter((i) => !i.is_paid);
  const nextInstallment = unpaid[0] ?? null;
  const remainingBalance = nextInstallment
    ? parseFloat(unpaid[0].remaining_balance) + parseFloat(unpaid[0].principal_amount)
    : 0;
  const paidCount = schedule.length - unpaid.length;
  const progress = schedule.length > 0 ? (paidCount / schedule.length) * 100 : 0;

  return (
    <div className="space-y-8">
      <div className="grid gap-6 md:grid-cols-3">
        <Card className="bg-card border-border">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs font-medium text-muted-foreground uppercase">Saldo Devedor</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold">{formatCurrency(remainingBalance)}</div>
            <Progress value={progress} className="h-1 mt-3" />
            <p className="text-xs text-muted-foreground mt-2">{paidCount} de {schedule.length} parcelas pagas</p>
          </CardContent>
        </Card>
        <Card className="bg-card border-border">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs font-medium text-muted-foreground uppercase">Próxima Parcela</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold">
              {nextInstallment ? formatCurrency(parseFloat(nextInstallment.total_amount)) : '—'}
            </div>
            {nextInstallment && (
              <p className="text-xs text-muted-foreground mt-1">
                Vence em {new Date(nextInstallment.due_date).toLocaleDateString('pt-BR')}
              </p>
            )}
          </CardContent>
        </Card>
        <Card className="bg-card border-border">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs font-medium text-muted-foreground uppercase">Economia se Quitar Hoje</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold text-emerald-500">
              {settlement ? formatCurrency(parseFloat(settlement.savings)) : '—'}
            </div>
            {settlement && (
              <p className="text-xs text-muted-foreground mt-1">
                Pagaria {formatCurrency(parseFloat(settlement.total_to_pay))} (valor presente)
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="bg-card border-border">
        <CardHeader>
          <CardTitle>Tabela {financing.method} — {financing.title}</CardTitle>
          <CardDescription>Visualização detalhada das parcelas e amortização.</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow className="border-border">
                <TableHead className="w-[50px]">Nº</TableHead>
                <TableHead>Vencimento</TableHead>
                <TableHead>Amortização</TableHead>
                <TableHead>Juros</TableHead>
                <TableHead>Total</TableHead>
                <TableHead className="text-right">Saldo Devedor</TableHead>
                <TableHead className="text-center">Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {schedule.map((row) => (
                <TableRow key={row.id} className="border-border">
                  <TableCell className="text-muted-foreground">{row.installment_number}</TableCell>
                  <TableCell>{new Date(row.due_date).toLocaleDateString('pt-BR')}</TableCell>
                  <TableCell>{formatCurrency(parseFloat(row.principal_amount))}</TableCell>
                  <TableCell>{formatCurrency(parseFloat(row.interest_amount))}</TableCell>
                  <TableCell className="font-medium">{formatCurrency(parseFloat(row.total_amount))}</TableCell>
                  <TableCell className="text-right text-muted-foreground">{formatCurrency(parseFloat(row.remaining_balance))}</TableCell>
                  <TableCell className="text-center">
                    {row.is_paid ? (
                      <StatusPill tone="success">Paga</StatusPill>
                    ) : row.installment_number === nextInstallment?.installment_number ? (
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 text-xs border-primary/40 text-primary hover:bg-primary/10"
                        onClick={async () => {
                          try {
                            await payInstallment({ financingId: financing.id, installmentNumber: row.installment_number });
                          } catch { toast.error('Erro ao pagar parcela.'); }
                        }}
                      >
                        Pagar
                      </Button>
                    ) : (
                      <StatusPill tone="neutral">Pendente</StatusPill>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

export function AmortizationTable() {
  const { financings, isLoading, remove } = useFinancing();
  const confirm = useConfirm();
  const [selectedId, setSelectedId] = React.useState<number | null>(null);
  const [createOpen, setCreateOpen] = React.useState(false);

  React.useEffect(() => {
    if (financings.length > 0 && !financings.some((f) => f.id === selectedId)) {
      setSelectedId(financings[0].id);
    }
    if (financings.length === 0) setSelectedId(null);
  }, [financings, selectedId]);

  const selected = financings.find((f) => f.id === selectedId) ?? null;

  if (isLoading) {
    return (
      <div className="h-[200px] flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3 flex-wrap">
          {financings.map((f) => (
            <button
              key={f.id}
              type="button"
              onClick={() => setSelectedId(f.id)}
              className={`px-4 py-2 rounded-xl border text-sm font-semibold transition-colors ${
                f.id === selectedId
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'border-border bg-card text-muted-foreground hover:text-foreground'
              }`}
            >
              {f.title}
              {f.status === 'settled' && <span className="ml-2 text-[10px] text-emerald-500 font-black">QUITADO</span>}
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          {selected && (
            <Button
              variant="ghost"
              className="text-destructive hover:bg-destructive/10 gap-2"
              onClick={async () => {
                const ok = await confirm({
                  title: 'Excluir financiamento',
                  description: `Excluir o financiamento "${selected.title}"?`,
                  confirmLabel: 'Excluir',
                  destructive: true,
                });
                if (!ok) return;
                try { await remove(selected.id); } catch { toast.error('Erro ao excluir.'); }
              }}
            >
              <Trash2 className="h-4 w-4" /> Excluir
            </Button>
          )}
          <Button onClick={() => setCreateOpen(true)} className="bg-primary hover:bg-primary/90 text-primary-foreground font-bold">
            + Novo Financiamento
          </Button>
        </div>
      </div>

      {financings.length === 0 ? (
        <Card className="bg-card border-border p-12 text-center">
          <p className="text-muted-foreground">
            Nenhum financiamento cadastrado. Crie um para ver o cronograma SAC/PRICE e simular quitação antecipada.
          </p>
        </Card>
      ) : selected ? (
        <FinancingDetail financing={selected} />
      ) : null}

      <CreateFinancingDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  );
}
