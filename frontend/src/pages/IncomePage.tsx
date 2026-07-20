import * as React from 'react';
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Plus, Edit2, Trash2, Calendar, Loader2, Wallet } from 'lucide-react';
import { useIncome, type Income } from '@/hooks/use-income';
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
import { MoneyInput } from "@/components/ui/MoneyInput";
import { formatCurrency } from '@/lib/money';

export function IncomePage() {
  const { incomes, isLoading, create, update, remove } = useIncome();
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [editingId, setEditingId] = React.useState<number | null>(null);
  const [title, setTitle] = React.useState('');
  const [amount, setAmount] = React.useState(0);
  const [receivedAt, setReceivedAt] = React.useState(() => new Date().toISOString().slice(0, 10));
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const openCreate = () => {
    setEditingId(null);
    setTitle('');
    setAmount(0);
    setReceivedAt(new Date().toISOString().slice(0, 10));
    setError(null);
    setDialogOpen(true);
  };

  const openEdit = (income: Income) => {
    setEditingId(income.id);
    setTitle(income.title);
    setAmount(parseFloat(income.amount));
    setReceivedAt(income.received_at.slice(0, 10));
    setError(null);
    setDialogOpen(true);
  };

  const handleSave = async () => {
    if (title.trim().length < 2 || amount <= 0) {
      setError('Preencha título e valor.');
      return;
    }
    setSaving(true);
    setError(null);
    const payload = {
      title: title.trim(),
      amount,
      received_at: new Date(`${receivedAt}T12:00:00`).toISOString(),
    };
    try {
      if (editingId) {
        await update({ id: editingId, data: payload });
      } else {
        await create(payload);
      }
      setDialogOpen(false);
    } catch {
      setError('Erro ao salvar a renda.');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm('Excluir esta renda? Os relatórios e a previsão serão recalculados.')) return;
    try {
      await remove(id);
    } catch {
      alert('Erro ao excluir a renda.');
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
    <div className="space-y-6 animate-in fade-in duration-500">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-foreground">Rendas</h2>
          <p className="text-muted-foreground">
            Salários e outras entradas do workspace — total registrado: <span className="font-bold text-emerald-500">{formatCurrency(total)}</span>
          </p>
        </div>
        <Button onClick={openCreate} className="gap-2 font-bold shadow-lg shadow-primary/20">
          <Plus className="h-4 w-4" /> Nova Renda
        </Button>
      </div>

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
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1.5 text-sm font-medium">
                      <Calendar className="h-3.5 w-3.5 text-primary" />
                      {new Date(income.received_at).toLocaleDateString('pt-BR')}
                    </div>
                  </TableCell>
                  <TableCell className="text-right">
                    <span className="font-black text-emerald-500">{formatCurrency(parseFloat(income.amount))}</span>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => openEdit(income)}
                        className="h-8 w-8 p-0 text-primary hover:bg-primary/10"
                      >
                        <Edit2 className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleDelete(income.id)}
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

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="bg-card border-border sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{editingId ? 'Editar Renda' : 'Nova Renda'}</DialogTitle>
            <DialogDescription>
              Registre salários e outras entradas para alimentar a previsão mensal.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
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
            </div>
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
