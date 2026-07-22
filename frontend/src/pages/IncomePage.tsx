import * as React from 'react';
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Plus, Edit2, Trash2, Calendar, Loader2, Wallet, Repeat } from 'lucide-react';
import { useIncome, type Income } from '@/hooks/use-income';
import { useRecurringIncome, type RecurringIncome } from '@/hooks/use-recurring-income';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { MoneyInput } from "@/components/ui/MoneyInput";
import { RecurrenceEditor } from "@/components/recurrence/RecurrenceEditor";
import {
  recurrenceLabel,
  defaultRecurrenceValue,
  recurrenceFromItem,
  toRecurrencePayload,
  type RecurrenceValue,
} from "@/lib/recurrence";
import { formatCurrency } from '@/lib/money';
import { getApiErrorMessage } from '@/lib/api-error';
import { toast } from '@/stores/toast';
import { useConfirm } from '@/components/ui/confirm';
import { PageHeader } from '@/components/layout/PageHeader';
import { MoneyText } from '@/components/money/MoneyText';

export function IncomePage() {
  const { incomes, isLoading, create, update, remove } = useIncome();
  const {
    recurringIncomes,
    isLoading: loadingRecurring,
    create: createRecurring,
    update: updateRecurring,
    remove: removeRecurring,
    generate,
    isGenerating,
  } = useRecurringIncome();
  const confirm = useConfirm();

  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<{ type: 'income' | 'recurring'; id: number } | null>(null);
  const [isRecurring, setIsRecurring] = React.useState(false);
  const [isActive, setIsActive] = React.useState(true);

  const [title, setTitle] = React.useState('');
  const [amount, setAmount] = React.useState(0);
  const [receivedAt, setReceivedAt] = React.useState(() => new Date().toISOString().slice(0, 10));
  const [recurrence, setRecurrence] = React.useState<RecurrenceValue>(defaultRecurrenceValue);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const patchRecurrence = (patch: Partial<RecurrenceValue>) =>
    setRecurrence((r) => ({ ...r, ...patch }));

  const resetForm = () => {
    setTitle('');
    setAmount(0);
    setReceivedAt(new Date().toISOString().slice(0, 10));
    setRecurrence(defaultRecurrenceValue());
    setIsActive(true);
    setError(null);
  };

  const openCreate = () => {
    setEditing(null);
    setIsRecurring(false);
    resetForm();
    setDialogOpen(true);
  };

  const openEditIncome = (income: Income) => {
    setEditing({ type: 'income', id: income.id });
    setIsRecurring(false);
    resetForm();
    setTitle(income.title);
    setAmount(parseFloat(income.amount));
    setReceivedAt(income.received_at.slice(0, 10));
    setDialogOpen(true);
  };

  const openEditRecurring = (item: RecurringIncome) => {
    setEditing({ type: 'recurring', id: item.id });
    setIsRecurring(true);
    resetForm();
    setTitle(item.title);
    setAmount(parseFloat(item.base_amount));
    setRecurrence(recurrenceFromItem(item));
    setIsActive(item.is_active);
    setDialogOpen(true);
  };

  const handleSave = async () => {
    if (title.trim().length < 2 || amount <= 0) {
      setError('Preencha título e valor.');
      return;
    }
    if (isRecurring && recurrence.custom && !recurrence.start_date) {
      setError('Escolha a data de início da recorrência personalizada.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (isRecurring) {
        const payload = {
          title: title.trim(),
          base_amount: amount,
          is_active: isActive,
          ...toRecurrencePayload(recurrence),
        };
        if (editing?.type === 'recurring') {
          await updateRecurring({ id: editing.id, data: payload });
        } else {
          await createRecurring(payload);
        }
      } else {
        const payload = {
          title: title.trim(),
          amount,
          received_at: new Date(`${receivedAt}T12:00:00`).toISOString(),
        };
        if (editing?.type === 'income') {
          await update({ id: editing.id, data: payload });
        } else {
          await create(payload);
        }
      }
      setDialogOpen(false);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Erro ao salvar a renda.'));
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteIncome = async (id: number) => {
    const ok = await confirm({
      title: 'Excluir renda',
      description: 'Excluir esta renda? Os relatórios e a previsão serão recalculados.',
      confirmLabel: 'Excluir',
      destructive: true,
    });
    if (!ok) return;
    try {
      await remove(id);
    } catch {
      toast.error('Erro ao excluir a renda.');
    }
  };

  const handleDeleteRecurring = async (id: number) => {
    const ok = await confirm({
      title: 'Excluir renda recorrente',
      description: 'Tem certeza? Isso não afeta as rendas já lançadas nos meses anteriores.',
      confirmLabel: 'Excluir',
      destructive: true,
    });
    if (!ok) return;
    try {
      await removeRecurring(id);
    } catch {
      toast.error('Erro ao excluir a renda recorrente.');
    }
  };

  const handleGenerate = async () => {
    try {
      const result = await generate();
      if (result.created > 0) {
        toast.success(`${result.created} renda(s) recorrente(s) lançada(s).`);
      } else {
        toast.info('Nenhuma renda recorrente pendente — tudo em dia.');
      }
    } catch (err) {
      toast.error(getApiErrorMessage(err, 'Erro ao lançar rendas pendentes.'));
    }
  };

  const total = incomes.reduce((acc, i) => acc + parseFloat(i.amount), 0);

  if (isLoading) {
    return (
      <div className="flex h-[400px] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Rendas"
        subtitle={`Salários e entradas do mês — total ${formatCurrency(total)}`}
        action={
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={handleGenerate} disabled={isGenerating} className="gap-2">
              {isGenerating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Repeat className="h-4 w-4" />}
              Lançar pendentes
            </Button>
            <Button onClick={openCreate} className="gap-2">
              <Plus className="h-4 w-4" /> Nova renda
            </Button>
          </div>
        }
      />

      <Card className="bg-card border-border shadow-xl">
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow className="border-border hover:bg-transparent">
                <TableHead className="w-[300px] text-muted-foreground font-bold uppercase tracking-wider text-[10px]">Título</TableHead>
                <TableHead className="text-muted-foreground font-bold uppercase tracking-wider text-[10px]">Recebida em</TableHead>
                <TableHead className="text-right text-muted-foreground font-bold uppercase tracking-wider text-[10px]">Valor</TableHead>
                <TableHead className="text-center text-muted-foreground font-bold uppercase tracking-wider text-[10px]">Ações</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {incomes.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="h-32 text-center text-muted-foreground">
                    Nenhuma renda registrada neste workspace.
                  </TableCell>
                </TableRow>
              ) : incomes.map((income) => (
                <TableRow key={income.id} className="border-border group hover:bg-accent/30 transition-colors">
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <Wallet className="h-4 w-4 text-emerald-500 shrink-0" />
                      <span className="font-bold text-foreground">{income.title}</span>
                      {income.recurring_income_id != null && (
                        <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-1.5 py-0.5 text-[9px] font-black uppercase text-primary">
                          <Repeat className="h-2.5 w-2.5" /> Recorrente
                        </span>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1.5 text-sm font-medium">
                      <Calendar className="h-3.5 w-3.5 text-primary" />
                      {new Date(income.received_at).toLocaleDateString('pt-BR')}
                    </div>
                  </TableCell>
                  <TableCell className="text-right">
                    <MoneyText value={income.amount} kind="income" className="font-semibold" />
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => openEditIncome(income)}
                        className="h-8 w-8 p-0 text-primary hover:bg-primary/10"
                      >
                        <Edit2 className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleDeleteIncome(income.id)}
                        className="h-8 w-8 p-0 text-destructive hover:bg-destructive/10"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Rendas recorrentes: templates que geram entradas mensais automáticas */}
      <div>
        <div className="mb-2 flex items-center gap-2">
          <Repeat className="h-4 w-4 text-primary" />
          <h3 className="text-lg font-bold tracking-tight text-foreground">Rendas recorrentes</h3>
        </div>
        <Card className="bg-card border-border shadow-xl">
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow className="border-border hover:bg-transparent">
                  <TableHead className="w-[300px] text-muted-foreground font-bold uppercase tracking-wider text-[10px]">Título</TableHead>
                  <TableHead className="text-muted-foreground font-bold uppercase tracking-wider text-[10px]">Recorrência</TableHead>
                  <TableHead className="text-muted-foreground font-bold uppercase tracking-wider text-[10px]">Status</TableHead>
                  <TableHead className="text-right text-muted-foreground font-bold uppercase tracking-wider text-[10px]">Valor</TableHead>
                  <TableHead className="text-center text-muted-foreground font-bold uppercase tracking-wider text-[10px]">Ações</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {loadingRecurring ? (
                  <TableRow>
                    <TableCell colSpan={5} className="h-20 text-center text-muted-foreground">
                      <Loader2 className="mx-auto h-5 w-5 animate-spin text-primary" />
                    </TableCell>
                  </TableRow>
                ) : recurringIncomes.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} className="h-24 text-center text-muted-foreground">
                      Nenhuma renda recorrente. Crie uma marcando "Recorrente" em Nova Renda.
                    </TableCell>
                  </TableRow>
                ) : recurringIncomes.map((item) => (
                  <TableRow key={item.id} className="border-border group hover:bg-accent/30 transition-colors">
                    <TableCell>
                      <span className="font-bold text-foreground">{item.title}</span>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1.5 text-sm font-medium">
                        <Calendar className="h-3.5 w-3.5 text-primary" />
                        {recurrenceLabel(item)}
                      </div>
                    </TableCell>
                    <TableCell>
                      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-black uppercase tracking-tighter ${
                        item.is_active
                          ? 'bg-emerald-500/10 text-emerald-500 border border-emerald-500/20'
                          : 'bg-muted text-muted-foreground border border-border'
                      }`}>
                        {item.is_active ? 'Ativa' : 'Inativa'}
                      </span>
                    </TableCell>
                    <TableCell className="text-right">
                      <MoneyText value={item.base_amount} kind="income" className="font-semibold" />
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => openEditRecurring(item)}
                          className="h-8 w-8 p-0 text-primary hover:bg-primary/10"
                        >
                          <Edit2 className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleDeleteRecurring(item.id)}
                          className="h-8 w-8 p-0 text-destructive hover:bg-destructive/10"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="bg-card border-border sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>
              {editing?.type === 'recurring'
                ? 'Editar Renda Recorrente'
                : editing?.type === 'income'
                  ? 'Editar Renda'
                  : 'Nova Renda'}
            </DialogTitle>
            <DialogDescription>
              Registre salários e outras entradas para alimentar a previsão mensal.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            {/* Toggle recorrente só na criação — evita converter tipo no meio do caminho */}
            {editing === null && (
              <div className="flex items-center justify-between p-3 rounded-lg bg-accent/30 border border-border">
                <div className="space-y-0.5">
                  <Label>Renda recorrente</Label>
                  <p className="text-[10px] text-muted-foreground font-medium">Gera uma entrada automática a cada período.</p>
                </div>
                <Switch checked={isRecurring} onCheckedChange={setIsRecurring} />
              </div>
            )}

            <div className="space-y-2">
              <Label htmlFor="income-title">Título</Label>
              <Input
                id="income-title"
                placeholder="Ex: Salário, Freelance..."
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className="bg-background/50"
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="income-amount">Valor</Label>
                <MoneyInput id="income-amount" value={amount} onChange={setAmount} className="bg-background/50" />
              </div>
              {!isRecurring && (
                <div className="space-y-2">
                  <Label htmlFor="income-date">Recebida em</Label>
                  <Input
                    id="income-date"
                    type="date"
                    value={receivedAt}
                    onChange={(e) => setReceivedAt(e.target.value)}
                    className="bg-background/50"
                  />
                </div>
              )}
            </div>

            {isRecurring && (
              <RecurrenceEditor value={recurrence} onChange={patchRecurrence} idPrefix="income" />
            )}

            {isRecurring && editing?.type === 'recurring' && (
              <div className="flex items-center justify-between p-3 rounded-lg bg-accent/30 border border-border">
                <div className="space-y-0.5">
                  <Label>Renda ativa</Label>
                  <p className="text-[10px] text-muted-foreground font-medium">Desative para pausar a geração automática.</p>
                </div>
                <Switch checked={isActive} onCheckedChange={setIsActive} />
              </div>
            )}

            {error && <p className="text-xs text-destructive font-medium">{error}</p>}
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setDialogOpen(false)}>Cancelar</Button>
            <Button type="button" onClick={handleSave} disabled={saving} className="bg-primary font-bold px-8">
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Salvar'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
