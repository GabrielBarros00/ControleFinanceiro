import * as React from 'react';
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Plus, Edit2, Trash2, Calendar, Repeat, Loader2 } from 'lucide-react';
import { useRecurring } from '@/hooks/use-recurring';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
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
import { getApiErrorMessage } from '@/lib/api-error';

const recurringSchema = z.object({
  title: z.string().min(1, 'Título é obrigatório'),
  description: z.string().optional(),
  base_amount: z.number().min(0.01, 'Valor deve ser maior que zero'),
  frequency: z.enum(['daily', 'weekly', 'monthly', 'yearly']),
  day_of_month: z.number().min(1).max(31),
  day_of_week: z.number().min(0).max(6),
  month_of_year: z.number().min(1).max(12),
  is_active: z.boolean(),
});

type RecurringValues = z.infer<typeof recurringSchema>;

interface RecurringItem {
  id: number;
  title: string;
  description?: string | null;
  base_amount: string;
  frequency: 'daily' | 'weekly' | 'monthly' | 'yearly';
  day_of_month: number;
  day_of_week?: number | null;
  month_of_year?: number | null;
  is_active: boolean;
}

const WEEKDAYS = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo'];
const MONTHS = [
  'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
  'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro',
];

function recurrenceLabel(item: RecurringItem): string {
  if (item.frequency === 'daily') {
    return 'Todo dia';
  }
  if (item.frequency === 'weekly') {
    return `Toda ${WEEKDAYS[item.day_of_week ?? 0]?.toLowerCase() ?? ''}`;
  }
  if (item.frequency === 'yearly') {
    return `Todo ano em ${item.day_of_month}/${String(item.month_of_year ?? 1).padStart(2, '0')}`;
  }
  return `Dia ${item.day_of_month}`;
}

const selectClass =
  'flex h-10 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring';

export function RecurringTransactionsPage() {
  const { recurring, isLoading, create, update, remove, generate, isGenerating } = useRecurring();
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [editingId, setEditingId] = React.useState<number | null>(null);

  const { register, handleSubmit, setValue, watch, reset, formState: { errors } } = useForm<RecurringValues>({
    resolver: zodResolver(recurringSchema),
    defaultValues: {
      is_active: true,
      frequency: 'monthly',
      day_of_month: 1,
      day_of_week: 0,
      month_of_year: 1,
    }
  });

  const baseAmount = watch('base_amount');
  const frequency = watch('frequency');

  const openCreate = () => {
    setEditingId(null);
    reset({
      title: '',
      description: '',
      base_amount: 0,
      frequency: 'monthly',
      day_of_month: 1,
      day_of_week: 0,
      month_of_year: 1,
      is_active: true,
    });
    setDialogOpen(true);
  };

  const openEdit = (item: RecurringItem) => {
    setEditingId(item.id);
    reset({
      title: item.title,
      description: item.description || '',
      base_amount: parseFloat(item.base_amount),
      frequency: item.frequency ?? 'monthly',
      day_of_month: item.day_of_month,
      day_of_week: item.day_of_week ?? 0,
      month_of_year: item.month_of_year ?? 1,
      is_active: item.is_active,
    });
    setDialogOpen(true);
  };

  const onSubmit = async (data: RecurringValues) => {
    // Envia só os campos relevantes para a frequência escolhida
    const payload = {
      title: data.title,
      description: data.description,
      base_amount: data.base_amount,
      frequency: data.frequency,
      day_of_month: data.day_of_month,
      day_of_week: data.frequency === 'weekly' ? data.day_of_week : null,
      month_of_year: data.frequency === 'yearly' ? data.month_of_year : null,
      is_active: data.is_active,
    };
    try {
      if (editingId) {
        await update({ id: editingId, data: payload });
      } else {
        await create(payload);
      }
      setDialogOpen(false);
    } catch (err) {
      alert(getApiErrorMessage(err, 'Erro ao salvar despesa recorrente'));
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm('Tem certeza que deseja excluir esta despesa recorrente? Isso não afetará transações já geradas.')) return;
    try {
      await remove(id);
    } catch (err) {
      alert(getApiErrorMessage(err, 'Erro ao excluir despesa recorrente'));
    }
  };

  const handleGenerate = async () => {
    try {
      const result = await generate();
      alert(result.created > 0
        ? `${result.created} lançamento(s) pendente(s) criado(s).`
        : 'Nenhum lançamento pendente — tudo em dia.');
    } catch (err) {
      alert(getApiErrorMessage(err, 'Erro ao lançar pendentes'));
    }
  };

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
          <h2 className="text-2xl font-bold tracking-tight text-foreground">Despesas Recorrentes</h2>
          <p className="text-muted-foreground">Gerencie seus gastos fixos mensais que são gerados automaticamente.</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={handleGenerate} disabled={isGenerating} className="gap-2 font-bold">
            {isGenerating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Repeat className="h-4 w-4" />}
            Lançar pendentes
          </Button>
          <Button onClick={openCreate} className="gap-2 font-bold shadow-lg shadow-primary/20">
            <Plus className="h-4 w-4" /> Nova Despesa
          </Button>
        </div>
      </div>

      <Card className="bg-card border-border shadow-xl">
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow className="border-border hover:bg-transparent">
                <TableHead className="w-[300px] text-muted-foreground font-bold uppercase tracking-wider text-[10px]">Descrição</TableHead>
                <TableHead className="text-muted-foreground font-bold uppercase tracking-wider text-[10px]">Recorrência</TableHead>
                <TableHead className="text-muted-foreground font-bold uppercase tracking-wider text-[10px]">Status</TableHead>
                <TableHead className="text-right text-muted-foreground font-bold uppercase tracking-wider text-[10px]">Valor Base</TableHead>
                <TableHead className="text-center text-muted-foreground font-bold uppercase tracking-wider text-[10px]">Ações</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {recurring.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="h-32 text-center text-muted-foreground">
                    Nenhuma despesa recorrente cadastrada.
                  </TableCell>
                </TableRow>
              ) : recurring.map((item: RecurringItem) => (
                <TableRow key={item.id} className="border-border group hover:bg-accent/30 transition-colors">
                  <TableCell>
                    <div className="flex flex-col">
                      <span className="font-bold text-foreground">{item.title}</span>
                      <span className="text-xs text-muted-foreground line-clamp-1">{item.description || 'Sem descrição'}</span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1.5 text-sm font-medium">
                      <Calendar className="h-3.5 w-3.5 text-primary" />
                      {recurrenceLabel(item)}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-black uppercase tracking-tighter ${
                      item.is_active 
                        ? 'bg-emerald-500/10 text-emerald-500 border border-emerald-500/20' 
                        : 'bg-muted text-muted-foreground border border-border'
                    }`}>
                      {item.is_active ? 'Ativo' : 'Inativo'}
                    </div>
                  </TableCell>
                  <TableCell className="text-right">
                    <span className="font-black text-foreground">
                      R$ {parseFloat(item.base_amount).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}
                    </span>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                      <Button 
                        variant="ghost" 
                        size="sm" 
                        onClick={() => openEdit(item)}
                        className="h-8 w-8 p-0 text-primary hover:bg-primary/10"
                      >
                        <Edit2 className="h-4 w-4" />
                      </Button>
                      <Button 
                        variant="ghost" 
                        size="sm" 
                        onClick={() => handleDelete(item.id)}
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
            <DialogTitle>{editingId ? 'Editar Despesa' : 'Nova Despesa Recorrente'}</DialogTitle>
            <DialogDescription>
              Configure os detalhes da sua despesa mensal automática.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="title">Título</Label>
              <div className="relative group">
                <Repeat className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground group-focus-within:text-primary" />
                <Input 
                  id="title" 
                  placeholder="Ex: Aluguel, Internet, Academia..." 
                  {...register('title')} 
                  className="pl-10 bg-background/50"
                />
              </div>
              {errors.title && <p className="text-xs text-destructive font-medium">{errors.title.message}</p>}
            </div>

            <div className="space-y-2">
              <Label htmlFor="description">Descrição (Opcional)</Label>
              <Input 
                id="description" 
                placeholder="Detalhes adicionais..." 
                {...register('description')} 
                className="bg-background/50"
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="base_amount">Valor Base</Label>
                <MoneyInput
                  id="base_amount"
                  value={baseAmount}
                  onChange={(val: number) => setValue('base_amount', val)}
                  className="bg-background/50"
                />
                {errors.base_amount && <p className="text-xs text-destructive font-medium">{errors.base_amount.message}</p>}
              </div>
              <div className="space-y-2">
                <Label htmlFor="frequency">Frequência</Label>
                <select id="frequency" className={selectClass} {...register('frequency')}>
                  <option value="monthly">Mensal</option>
                  <option value="weekly">Semanal</option>
                  <option value="daily">Diária</option>
                  <option value="yearly">Anual</option>
                </select>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              {frequency === 'weekly' ? (
                <div className="space-y-2">
                  <Label htmlFor="day_of_week">Dia da Semana</Label>
                  <select id="day_of_week" className={selectClass} {...register('day_of_week', { valueAsNumber: true })}>
                    {WEEKDAYS.map((name, idx) => (
                      <option key={idx} value={idx}>{name}</option>
                    ))}
                  </select>
                </div>
              ) : (
                <div className="space-y-2">
                  <Label htmlFor="day_of_month">Dia do Vencimento</Label>
                  <div className="relative group">
                    <Calendar className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground group-focus-within:text-primary" />
                    <Input
                      id="day_of_month"
                      type="number"
                      min={1}
                      max={31}
                      {...register('day_of_month', { valueAsNumber: true })}
                      className="pl-10 bg-background/50"
                    />
                  </div>
                  {errors.day_of_month && <p className="text-xs text-destructive font-medium">{errors.day_of_month.message}</p>}
                </div>
              )}
              {frequency === 'yearly' && (
                <div className="space-y-2">
                  <Label htmlFor="month_of_year">Mês do Ano</Label>
                  <select id="month_of_year" className={selectClass} {...register('month_of_year', { valueAsNumber: true })}>
                    {MONTHS.map((name, idx) => (
                      <option key={idx} value={idx + 1}>{name}</option>
                    ))}
                  </select>
                </div>
              )}
            </div>

            <div className="flex items-center justify-between p-3 rounded-lg bg-accent/30 border border-border">
              <div className="space-y-0.5">
                <Label>Despesa Ativa</Label>
                <p className="text-[10px] text-muted-foreground font-medium">Desative para pausar a geração automática.</p>
              </div>
              <Switch 
                checked={watch('is_active')} 
                onCheckedChange={(val) => setValue('is_active', val)} 
              />
            </div>
            
            <DialogFooter className="pt-4">
              <Button type="button" variant="ghost" onClick={() => setDialogOpen(false)}>Cancelar</Button>
              <Button type="submit" className="bg-primary font-bold px-8">Salvar</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
