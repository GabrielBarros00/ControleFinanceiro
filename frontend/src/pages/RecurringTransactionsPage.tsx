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
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { MoneyInput } from "@/components/ui/MoneyInput";
import { CurrencyCombobox } from "@/components/dashboard/transaction-form/CurrencyCombobox";
import { currencySymbol, formatCurrency } from "@/lib/money";
import { useBaseCurrency } from '@/hooks/use-base-currency';
import { RecurrenceEditor } from "@/components/recurrence/RecurrenceEditor";
import { MaterializeScopeField } from "@/components/recurrence/MaterializeScopeField";
import {
  recurrenceLabel,
  recurrenceFromItem,
  toRecurrencePayload,
  isRetroactiveStart,
  type MaterializeScope,
  type RecurrenceValue,
} from "@/lib/recurrence";
import { useCategories } from '@/hooks/use-categories';
import { useCreditCards } from '@/hooks/use-credit-cards';
import { PAYMENT_METHOD_OPTIONS, paymentMethodLabel } from '@/lib/payment-methods';
import { getApiErrorMessage } from '@/lib/api-error';
import { toast } from '@/stores/toast';
import { useConfirm } from '@/components/ui/confirm';
import { todayLocalISO } from '@/lib/date';
import { PageHeader } from '@/components/layout/PageHeader';

// Base UI Select foge do focus-trap do Dialog (Radix) — dentro de modal usamos
// <select> nativo, mesmo padrão de AmortizationTable/PaymentMethodField.
const selectClass =
  'flex h-10 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring';

const recurringSchema = z.object({
  title: z.string().min(1, 'Título é obrigatório'),
  description: z.string().optional(),
  base_amount: z.number().min(0.01, 'Valor deve ser maior que zero'),
  currency: z.string(),
  // 0 = "Sem categoria" (o <select> nativo só carrega string; vira null no payload)
  category_id: z.number(),
  payment_method: z.string(),
  // 0 = nenhum cartão; só vale com payment_method === 'credit_card' (o backend recusa o resto)
  credit_card_id: z.number(),
  custom: z.boolean(),
  frequency: z.enum(['daily', 'weekly', 'monthly', 'yearly']),
  interval: z.number().min(1),
  start_date: z.string(),
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
  currency?: string | null;
  category_id?: number | null;
  payment_method?: string | null;
  credit_card_id?: number | null;
  frequency: 'daily' | 'weekly' | 'monthly' | 'yearly';
  interval?: number | null;
  start_date?: string | null;
  day_of_month: number;
  day_of_week?: number | null;
  month_of_year?: number | null;
  is_active: boolean;
}

const todayStr = todayLocalISO;

const DEFAULTS: RecurringValues = {
  title: '',
  description: '',
  base_amount: 0,
  // Preenchida com a moeda-base do workspace ao abrir o form (ver reset abaixo)
  currency: '',
  category_id: 0,
  payment_method: '',
  credit_card_id: 0,
  custom: false,
  frequency: 'monthly',
  interval: 1,
  start_date: todayStr(),
  day_of_month: 1,
  day_of_week: 0,
  month_of_year: 1,
  is_active: true,
};

export function RecurringTransactionsPage() {
  const { recurring, isLoading, create, update, remove, generate, isGenerating } = useRecurring();
  const { categories, categoryName } = useCategories();
  const baseCurrency = useBaseCurrency();
  const { cards } = useCreditCards();
  const confirm = useConfirm();
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [editingId, setEditingId] = React.useState<number | null>(null);
  // Alcance da edição sobre as instâncias já geradas (não pagas)
  const [editScope, setEditScope] = React.useState<'none' | 'future' | 'all'>('future');
  // Alcance da materialização quando a data de início é retroativa
  const [materialize, setMaterialize] = React.useState<MaterializeScope>('current');

  const { register, handleSubmit, setValue, watch, reset, formState: { errors } } = useForm<RecurringValues>({
    resolver: zodResolver(recurringSchema),
    defaultValues: DEFAULTS,
  });

  const baseAmount = watch('base_amount');
  const currency = watch('currency');
  const paymentMethod = watch('payment_method');

  // Sair do crédito solta o cartão: o backend recusa pix/boleto com cartão preso
  React.useEffect(() => {
    if (paymentMethod !== 'credit_card') setValue('credit_card_id', 0);
  }, [paymentMethod, setValue]);

  // Ponte entre o react-hook-form e o RecurrenceEditor (controlado)
  const recurrence: RecurrenceValue = {
    custom: watch('custom'),
    frequency: watch('frequency'),
    interval: watch('interval'),
    start_date: watch('start_date'),
    day_of_week: watch('day_of_week'),
    day_of_month: watch('day_of_month'),
    month_of_year: watch('month_of_year'),
  };
  const patchRecurrence = (patch: Partial<RecurrenceValue>) => {
    (Object.entries(patch) as [keyof RecurrenceValue, RecurrenceValue[keyof RecurrenceValue]][])
      .forEach(([k, v]) => setValue(k, v as never));
  };

  const openCreate = () => {
    setEditingId(null);
    setEditScope('future');
    setMaterialize('current');
    reset({ ...DEFAULTS, currency: baseCurrency, start_date: todayStr() });
    setDialogOpen(true);
  };

  const openEdit = (item: RecurringItem) => {
    setEditingId(item.id);
    setEditScope('future');
    setMaterialize('current');
    const rec = recurrenceFromItem(item);
    reset({
      title: item.title,
      description: item.description || '',
      base_amount: parseFloat(item.base_amount),
      currency: item.currency ?? baseCurrency,
      category_id: item.category_id ?? 0,
      payment_method: item.payment_method ?? '',
      credit_card_id: item.credit_card_id ?? 0,
      is_active: item.is_active,
      ...rec,
    });
    setDialogOpen(true);
  };

  const onSubmit = async (data: RecurringValues) => {
    if (data.custom && !data.start_date) {
      toast.error('Escolha a data de início da recorrência personalizada.');
      return;
    }
    const recValue: RecurrenceValue = {
      custom: data.custom,
      frequency: data.frequency,
      interval: data.interval,
      start_date: data.start_date,
      day_of_week: data.day_of_week,
      day_of_month: data.day_of_month,
      month_of_year: data.month_of_year,
    };
    const payload = {
      title: data.title,
      description: data.description,
      base_amount: data.base_amount,
      currency: data.currency || baseCurrency,
      // A categoria segue para cada instância materializada (RecurringService._apply_category)
      category_id: data.category_id > 0 ? data.category_id : null,
      payment_method: data.payment_method || null,
      // Cartão só acompanha o crédito — o backend rejeita a combinação inválida
      credit_card_id:
        data.payment_method === 'credit_card' && data.credit_card_id > 0 ? data.credit_card_id : null,
      is_active: data.is_active,
      ...toRecurrencePayload(recValue),
    };
    // `materialize` só viaja quando a pergunta foi feita; senão o backend usa o
    // padrão 'current' (mês corrente) e o histórico fica intocado.
    const scope = isRetroactiveStart(data.start_date) ? materialize : undefined;
    try {
      if (editingId) {
        await update({ id: editingId, data: payload, scope: editScope, materialize: scope });
      } else {
        await create({ data: payload, materialize: scope });
      }
      setDialogOpen(false);
    } catch (err) {
      toast.error(getApiErrorMessage(err, 'Erro ao salvar despesa recorrente'));
    }
  };

  const handleDelete = async (id: number) => {
    const ok = await confirm({
      title: 'Excluir despesa recorrente',
      description: 'Tem certeza? Isso não afetará transações já geradas.',
      confirmLabel: 'Excluir',
      destructive: true,
    });
    if (!ok) return;
    try {
      await remove(id);
    } catch (err) {
      toast.error(getApiErrorMessage(err, 'Erro ao excluir despesa recorrente'));
    }
  };

  const handleGenerate = async () => {
    try {
      const result = await generate();
      if (result.created > 0) {
        toast.success(`${result.created} lançamento(s) pendente(s) criado(s).`);
      } else {
        toast.info('Nenhum lançamento pendente — tudo em dia.');
      }
    } catch (err) {
      toast.error(getApiErrorMessage(err, 'Erro ao lançar pendentes'));
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
      {/* `h1` num `<header>`, como as demais telas: esta era mais uma sem
          cabeçalho de página — só um `h2` solto, então o documento começava no
          nível 2 e a navegação por títulos não tinha âncora. */}
      <PageHeader
        title="Recorrência"
        subtitle="Seus gastos fixos, gerados automaticamente todo mês."
      />
      <div className="flex items-center justify-end">
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
                <TableHead className="w-[300px] text-muted-foreground font-semibold text-xs">Descrição</TableHead>
                <TableHead className="text-muted-foreground font-semibold text-xs">Recorrência</TableHead>
                <TableHead className="text-muted-foreground font-semibold text-xs">Status</TableHead>
                <TableHead className="text-right text-muted-foreground font-semibold text-xs">Valor Base</TableHead>
                <TableHead className="text-center text-muted-foreground font-semibold text-xs">Ações</TableHead>
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
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-foreground">{item.title}</span>
                        {item.category_id != null && (
                          <span className="rounded-full bg-primary/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase text-primary">
                            {categoryName(item.category_id)}
                          </span>
                        )}
                      </div>
                      <span className="text-xs text-muted-foreground line-clamp-1">
                        {[
                          paymentMethodLabel(item.payment_method, item.credit_card_id),
                          item.credit_card_id != null
                            ? (cards as { id: number; name: string }[]).find((c) => c.id === item.credit_card_id)?.name
                            : null,
                          item.description || null,
                        ].filter(Boolean).join(' · ')}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1.5 text-sm font-medium">
                      <Calendar className="h-3.5 w-3.5 text-primary" />
                      {recurrenceLabel(item)}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-tighter ${
                      item.is_active
                        ? 'bg-emerald-500/10 text-emerald-500 border border-emerald-500/20'
                        : 'bg-muted text-muted-foreground border border-border'
                    }`}>
                      {item.is_active ? 'Ativo' : 'Inativo'}
                    </div>
                  </TableCell>
                  <TableCell className="text-right">
                    <span className="font-semibold text-foreground">
                      {formatCurrency(parseFloat(item.base_amount), item.currency ?? baseCurrency)}
                    </span>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-center gap-2 transition-opacity sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100">
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Editar recorrência ${item.title}`}
                        onClick={() => openEdit(item)}
                        className="h-8 w-8 p-0 text-primary hover:bg-primary/10"
                      >
                        <Edit2 className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Excluir recorrência ${item.title}`}
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
              Configure os detalhes da sua despesa automática.
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
              <Textarea
                id="description"
                rows={3}
                placeholder="Detalhes adicionais..."
                {...register('description')}
                className="bg-background/50"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="base_amount">Valor Base</Label>
              <div className="flex gap-2">
                <MoneyInput
                  id="base_amount"
                  value={baseAmount}
                  onChange={(val: number) => setValue('base_amount', val)}
                  prefix={currencySymbol(currency)}
                  className="bg-background/50 flex-1"
                />
                <CurrencyCombobox value={currency} onChange={(c) => setValue('currency', c, { shouldValidate: true })} />
              </div>
              {errors.base_amount && <p className="text-xs text-destructive font-medium">{errors.base_amount.message}</p>}
              {/* "Estrangeira" é != da moeda-BASE, não != 'BRL' */}
              {currency && currency !== baseCurrency && (
                <p className="text-[11px] font-medium text-muted-foreground">
                  Recorrência em moeda estrangeira: converte para {baseCurrency} a cada mês, com a taxa do dia.
                </p>
              )}
            </div>

            {/* Categoria: o modelo propaga para cada lançamento gerado, então sem
                ela a despesa fixa some dos gráficos por categoria. */}
            <div className="space-y-2">
              <Label htmlFor="rec-category">Categoria</Label>
              <select
                id="rec-category"
                value={watch('category_id')}
                onChange={(e) => setValue('category_id', Number(e.target.value))}
                className={selectClass}
              >
                <option value={0} className="bg-card">Sem categoria</option>
                {categories.map((cat) => (
                  <option key={cat.id} value={cat.id} className="bg-card">{cat.name}</option>
                ))}
              </select>
            </div>

            {/* Forma de pagamento + cartão: no crédito, cada ocorrência é roteada
                para a fatura do ciclo dela — sem isso a assinatura ficava fora
                da fatura e do limite comprometido. */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label htmlFor="rec-payment-method">Forma de pagamento</Label>
                <select id="rec-payment-method" className={selectClass} {...register('payment_method')}>
                  <option value="" className="bg-card">Não informado</option>
                  {PAYMENT_METHOD_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value} className="bg-card">{opt.label}</option>
                  ))}
                </select>
              </div>
              {paymentMethod === 'credit_card' && (
                <div className="space-y-2">
                  <Label htmlFor="rec-card">Qual cartão?</Label>
                  <select
                    id="rec-card"
                    className={selectClass}
                    value={watch('credit_card_id')}
                    onChange={(e) => setValue('credit_card_id', Number(e.target.value))}
                  >
                    <option value={0} className="bg-card">Sem cartão</option>
                    {(cards as { id: number; name: string }[]).map((card) => (
                      <option key={card.id} value={card.id} className="bg-card">{card.name}</option>
                    ))}
                  </select>
                </div>
              )}
            </div>

            <RecurrenceEditor value={recurrence} onChange={patchRecurrence} idPrefix="rec" />

            {isRetroactiveStart(watch('start_date')) && (
              <MaterializeScopeField
                value={materialize}
                onChange={setMaterialize}
                kind="expense"
                idPrefix="rec"
              />
            )}

            {editingId && (
              <div className="space-y-2 rounded-lg bg-accent/30 border border-border p-3">
                <Label htmlFor="edit-scope">Aplicar alterações a</Label>
                <select
                  id="edit-scope"
                  value={editScope}
                  onChange={(e) => setEditScope(e.target.value as 'none' | 'future' | 'all')}
                  className="flex h-10 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                >
                  <option value="future">Deste mês em diante (lançamentos não pagos)</option>
                  <option value="all">Todos os lançamentos não pagos</option>
                  <option value="none">Só o modelo (não mexer nos lançamentos)</option>
                </select>
                <p className="text-[10px] text-muted-foreground font-medium">
                  Lançamentos já pagos nunca são alterados.
                </p>
              </div>
            )}

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
