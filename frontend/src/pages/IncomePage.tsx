import * as React from 'react';
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Plus, Edit2, Trash2, Calendar, Check, Loader2, Wallet, Repeat } from 'lucide-react';
import { INCOME_STATUS_LABEL, useIncome, type Income } from '@/hooks/use-income';
import { StatusPill } from '@/components/ui/status-pill';
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
import { MaterializeScopeField } from "@/components/recurrence/MaterializeScopeField";
import {
  recurrenceLabel,
  defaultRecurrenceValue,
  recurrenceFromItem,
  toRecurrencePayload,
  isRetroactiveStart,
  type MaterializeScope,
  type RecurrenceValue,
} from "@/lib/recurrence";
import { formatCurrency, currencySymbol } from '@/lib/money';
import { useReportCurrency } from '@/hooks/use-report-currency';
import { CurrencyCombobox } from '@/components/dashboard/transaction-form/CurrencyCombobox';
import { getApiErrorMessage } from '@/lib/api-error';
import { toast } from '@/stores/toast';
import { useConfirm } from '@/components/ui/confirm';
import { PageHeader } from '@/components/layout/PageHeader';
import { PeriodPicker } from '@/components/layout/PeriodPicker';
import { MoneyText } from '@/components/money/MoneyText';
import { parseApiDate, todayLocalISO } from '@/lib/date';
import { useMonthParam } from '@/hooks/use-month-param';
import { CardsOrTable, DataCard } from '@/components/ui/data-card';
import { NativeSelect } from '@/components/ui/native-select';
import { usePaymentAccounts } from '@/hooks/use-payment-accounts';


/**
 * A pílula de estado da renda (ADR 0034).
 *
 * `status` vem do SERVIDOR, derivado de `settled_at`/`cancelled_at`/`received_at`.
 * Nunca recalcule aqui: "atrasada" depende de qual é hoje, e o fuso do navegador
 * dá outra resposta perto da meia-noite.
 */
function IncomeStatusPill({ status }: { status?: string | null }) {
  if (status === 'received' || !status) return null;
  const tom =
    status === 'overdue' ? 'warning' : status === 'cancelled' ? 'neutral' : 'brand';
  return (
    <StatusPill tone={tom as 'warning' | 'neutral' | 'brand'}>
      {INCOME_STATUS_LABEL[status] ?? status}
    </StatusPill>
  );
}

/** "Recebida em 30/09" × "prevista para 30/09" — a data é a mesma, o fato não. */
function rotuloDeData(income: Income): string {
  const dia = parseApiDate(income.settled_at ?? income.received_at).toLocaleDateString('pt-BR');
  if (income.status === 'received') return `Recebida em ${dia}`;
  if (income.status === 'cancelled') return `Cancelada — era para ${dia}`;
  if (income.status === 'overdue') return `Era para entrar em ${dia}`;
  return `Prevista para ${dia}`;
}

export function IncomePage() {
  const [month, setMonth] = useMonthParam();
  const { incomes, isLoading, create, update, remove, receive, unreceive, cancel } =
    useIncome(month);
  // A conta em que a renda cai — opcional, como no pagamento de conta: registrar
  // o recebimento sem dizer onde caiu continua valendo, só não move saldo.
  const { activeAccounts } = usePaymentAccounts();
  const [recebendo, setRecebendo] = React.useState<Income | null>(null);
  // Renda é PESSOAL (ADR 0021): a moeda é a de relatório do usuário, não a
  // moeda-base do workspace aberto. Somar `amount` e formatar com a base do
  // workspace fazia a MESMA renda ser exibida em moedas diferentes conforme a
  // casa em que a tela por acaso estivesse.
  const baseCurrency = useReportCurrency();
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
  const [receivedAt, setReceivedAt] = React.useState(todayLocalISO);
  // Moeda-base do workspace, não 'BRL' fixo: num workspace em USD o default
  // fazia o backend tratar toda renda comum como ESTRANGEIRA (e converter
  // com taxa 1). `useState(fn)` porque o valor vem de hook, não de literal.
  const [currency, setCurrency] = React.useState(baseCurrency);
  const [recurrence, setRecurrence] = React.useState<RecurrenceValue>(defaultRecurrenceValue);
  // Só usado quando a data de início é retroativa (ver MaterializeScopeField)
  const [materialize, setMaterialize] = React.useState<MaterializeScope>('current');
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const retroactive = isRecurring && isRetroactiveStart(recurrence.start_date);

  const patchRecurrence = (patch: Partial<RecurrenceValue>) =>
    setRecurrence((r) => ({ ...r, ...patch }));

  const resetForm = () => {
    setTitle('');
    setAmount(0);
    setReceivedAt(todayLocalISO());
    setCurrency(baseCurrency);
    setRecurrence(defaultRecurrenceValue());
    setIsActive(true);
    setMaterialize('current');
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
    // Estrangeira: edita o valor/moeda ORIGINAIS (o backend re-converte no save)
    setAmount(income.original_amount ? parseFloat(income.original_amount) : parseFloat(income.amount));
    setCurrency(income.original_currency ?? income.currency ?? baseCurrency);
    setReceivedAt(income.received_at.slice(0, 10));
    setDialogOpen(true);
  };

  const openEditRecurring = (item: RecurringIncome) => {
    setEditing({ type: 'recurring', id: item.id });
    setIsRecurring(true);
    resetForm();
    setTitle(item.title);
    setAmount(parseFloat(item.base_amount));
    setCurrency(item.currency ?? baseCurrency);
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
          currency,
          is_active: isActive,
          ...toRecurrencePayload(recurrence),
        };
        // `materialize` só viaja quando a pergunta foi feita; senão o backend
        // usa o padrão 'current' (mês corrente) e nada muda no histórico.
        const scope = retroactive ? materialize : undefined;
        if (editing?.type === 'recurring') {
          await updateRecurring({ id: editing.id, data: payload, materialize: scope });
        } else {
          await createRecurring({ data: payload, materialize: scope });
        }
      } else {
        const payload = {
          title: title.trim(),
          amount,
          currency,
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
      <div className="flex h-[240px] items-center justify-center sm:h-[400px]">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Rendas"
        // "em todos os workspaces" descrevia errado o próprio modelo: desde o
        // ADR 0021 a renda não mora em workspace nenhum — ela é da pessoa, e só
        // ela a vê. Dizer que está "em todos" sugeria exatamente o oposto.
        subtitle={`Suas entradas do mês, só suas — total ${formatCurrency(total, baseCurrency)}`}
        period={<PeriodPicker value={month} onChange={setMonth} />}
        action={
          <div className="flex flex-wrap items-center gap-2">
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

      {/* Celular: um cartão por renda. A tabela tem quatro colunas e a coluna
          de VALOR — a razão de a pessoa abrir a tela — caía fora da área
          visível, atrás de um scroll horizontal sem nenhuma pista de que
          existia (ver screenshots/mobile-rendas-*.png antes desta rodada). */}
      <CardsOrTable
        cards={
      <div className="space-y-2">
        {incomes.length === 0 ? (
          <p className="rounded-xl border border-border bg-card p-6 text-center text-sm text-muted-foreground">
            Nenhuma renda registrada neste mês.
          </p>
        ) : incomes.map((income) => (
          <DataCard
            key={income.id}
            title={income.title}
            badge={
              <span className="inline-flex items-center gap-1">
                <IncomeStatusPill status={income.status} />
                {income.recurring_income_id != null && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase text-primary">
                    <Repeat className="h-2.5 w-2.5" /> Recorrente
                  </span>
                )}
              </span>
            }
            meta={rotuloDeData(income)}
            value={
              <>
                {/* Prevista em tom secundário: ela é renda do mês (competência),
                    e não dinheiro em mãos. Mostrá-la com o mesmo peso da recebida
                    é o que fazia o app afirmar em 01/09 que os R$ 6.000 do dia 30
                    já tinham entrado. */}
                <MoneyText
                  value={income.amount}
                  kind="income"
                  className={income.status === 'received' ? 'font-semibold' : 'font-semibold opacity-60'}
                />
                {income.original_currency && income.original_amount && (
                  <div className="text-[11px] text-muted-foreground">
                    {formatCurrency(parseFloat(income.original_amount), income.original_currency)}
                  </div>
                )}
              </>
            }
            actions={
              <>
                {income.status !== 'received' && income.status !== 'cancelled' && (
                  <Button
                    size="sm"
                    aria-label={`Confirmar o recebimento de ${income.title}`}
                    onClick={() => setRecebendo(income)}
                    className="h-10 flex-1 gap-2"
                  >
                    <Check className="h-4 w-4" /> Recebi
                  </Button>
                )}
                <Button
                  variant="outline"
                  size="sm"
                  aria-label={`Editar renda ${income.title}`}
                  onClick={() => openEditIncome(income)}
                  className="h-10 flex-1 gap-2"
                >
                  <Edit2 className="h-4 w-4" /> Editar
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  aria-label={`Excluir renda ${income.title}`}
                  onClick={() => handleDeleteIncome(income.id)}
                  className="h-10 w-10 p-0 text-destructive"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </>
            }
          />
        ))}
      </div>
        }
        table={
      <Card className="bg-card border-border shadow-xl">
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow className="border-border hover:bg-transparent">
                <TableHead className="w-[300px] text-muted-foreground font-semibold text-xs">Título</TableHead>
                <TableHead className="text-muted-foreground font-semibold text-xs">Quando</TableHead>
                <TableHead className="text-right text-muted-foreground font-semibold text-xs">Valor</TableHead>
                <TableHead className="text-center text-muted-foreground font-semibold text-xs">Ações</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {incomes.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="h-32 text-center text-muted-foreground">
                    Nenhuma renda registrada neste mês.
                  </TableCell>
                </TableRow>
              ) : incomes.map((income) => (
                <TableRow key={income.id} className="border-border group hover:bg-accent/30 transition-colors">
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <Wallet className="h-4 w-4 text-emerald-500 shrink-0" />
                      <span className="font-bold text-foreground">{income.title}</span>
                      <IncomeStatusPill status={income.status} />
                      {income.recurring_income_id != null && (
                        <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase text-primary">
                          <Repeat className="h-2.5 w-2.5" /> Recorrente
                        </span>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1.5 text-sm font-medium">
                      <Calendar className="h-3.5 w-3.5 text-primary" />
                      {rotuloDeData(income)}
                    </div>
                  </TableCell>
                  <TableCell className="text-right">
                    <MoneyText
                      value={income.amount}
                      kind="income"
                      className={income.status === 'received' ? 'font-semibold' : 'font-semibold opacity-60'}
                    />
                    {income.original_currency && income.original_amount && (
                      <div className="text-[11px] text-muted-foreground">
                        {formatCurrency(parseFloat(income.original_amount), income.original_currency)}
                      </div>
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-center gap-2 transition-opacity sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100">
                      {income.status !== 'received' && income.status !== 'cancelled' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Confirmar o recebimento de ${income.title}`}
                          onClick={() => setRecebendo(income)}
                          className="h-8 gap-1 text-xs"
                        >
                          <Check className="h-3.5 w-3.5" /> Recebi
                        </Button>
                      )}
                      {income.status === 'received' && income.recurring_income_id != null && (
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Desfazer o recebimento de ${income.title}`}
                          onClick={async () => {
                            try {
                              await unreceive(income.id);
                              toast.success('Recebimento desfeito.');
                            } catch (err) {
                              toast.error(getApiErrorMessage(err, 'Erro ao desfazer.'));
                            }
                          }}
                          className="h-8 text-xs"
                        >
                          Desfazer
                        </Button>
                      )}
                      {income.status !== 'cancelled' && income.recurring_income_id != null && (
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Cancelar a renda ${income.title}`}
                          onClick={async () => {
                            try {
                              await cancel(income.id);
                              toast.success('Renda cancelada — ela continua visível no mês.');
                            } catch (err) {
                              toast.error(getApiErrorMessage(err, 'Erro ao cancelar.'));
                            }
                          }}
                          className="h-8 text-xs"
                        >
                          Cancelar
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Editar renda ${income.title}`}
                        onClick={() => openEditIncome(income)}
                        className="h-8 w-8 p-0 text-primary hover:bg-primary/10"
                      >
                        <Edit2 className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Excluir renda ${income.title}`}
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
        }
      />

      {/* Rendas recorrentes: templates que geram entradas mensais automáticas */}
      <div>
        <div className="mb-2 flex items-center gap-2">
          <Repeat className="h-4 w-4 text-primary" />
          <h3 className="text-lg font-bold tracking-tight text-foreground">Rendas recorrentes</h3>
        </div>
        <CardsOrTable
          cards={
        <div className="space-y-2">
          {loadingRecurring ? (
            <div className="rounded-xl border border-border bg-card p-6 text-center">
              <Loader2 className="mx-auto h-5 w-5 animate-spin text-primary" />
            </div>
          ) : recurringIncomes.length === 0 ? (
            <p className="rounded-xl border border-border bg-card p-6 text-center text-sm text-muted-foreground">
              Nenhuma renda recorrente. Crie uma marcando "Recorrente" em Nova Renda.
            </p>
          ) : recurringIncomes.map((item) => (
            <DataCard
              key={item.id}
              title={item.title}
              badge={
                <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${
                  item.is_active
                    ? 'border border-emerald-500/20 bg-emerald-500/10 text-emerald-500'
                    : 'border border-border bg-muted text-muted-foreground'
                }`}>
                  {item.is_active ? 'Ativa' : 'Inativa'}
                </span>
              }
              meta={recurrenceLabel(item)}
              value={<MoneyText value={item.base_amount} kind="income" currency={item.currency} className="font-semibold" />}
              actions={
                <>
                  <Button
                    variant="outline"
                    size="sm"
                    aria-label={`Editar renda recorrente ${item.title}`}
                    onClick={() => openEditRecurring(item)}
                    className="h-10 flex-1 gap-2"
                  >
                    <Edit2 className="h-4 w-4" /> Editar
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    aria-label={`Excluir renda recorrente ${item.title}`}
                    onClick={() => handleDeleteRecurring(item.id)}
                    className="h-10 w-10 p-0 text-destructive"
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </>
              }
            />
          ))}
        </div>
          }
          table={
        <Card className="bg-card border-border shadow-xl">
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow className="border-border hover:bg-transparent">
                  <TableHead className="w-[300px] text-muted-foreground font-semibold text-xs">Título</TableHead>
                  <TableHead className="text-muted-foreground font-semibold text-xs">Recorrência</TableHead>
                  <TableHead className="text-muted-foreground font-semibold text-xs">Status</TableHead>
                  <TableHead className="text-right text-muted-foreground font-semibold text-xs">Valor</TableHead>
                  <TableHead className="text-center text-muted-foreground font-semibold text-xs">Ações</TableHead>
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
                      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-tighter ${
                        item.is_active
                          ? 'bg-emerald-500/10 text-emerald-500 border border-emerald-500/20'
                          : 'bg-muted text-muted-foreground border border-border'
                      }`}>
                        {item.is_active ? 'Ativa' : 'Inativa'}
                      </span>
                    </TableCell>
                    <TableCell className="text-right">
                      <MoneyText value={item.base_amount} kind="income" currency={item.currency} className="font-semibold" />
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-center gap-2 transition-opacity sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100">
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Editar renda recorrente ${item.title}`}
                          onClick={() => openEditRecurring(item)}
                          className="h-8 w-8 p-0 text-primary hover:bg-primary/10"
                        >
                          <Edit2 className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Excluir renda recorrente ${item.title}`}
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
          }
        />
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

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="income-amount">Valor</Label>
                <div className="flex gap-2">
                  <MoneyInput id="income-amount" value={amount} onChange={setAmount} prefix={currencySymbol(currency)} className="bg-background/50 flex-1" />
                  <CurrencyCombobox value={currency} onChange={setCurrency} />
                </div>
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

            {retroactive && (
              <MaterializeScopeField
                value={materialize}
                onChange={setMaterialize}
                kind="income"
                idPrefix="income"
              />
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

      {recebendo && (
        <ConfirmarRecebimentoDialog
          income={recebendo}
          contas={activeAccounts.filter((c) => c.currency === (recebendo.currency ?? baseCurrency))}
          onClose={() => setRecebendo(null)}
          onConfirm={async (receivedOn, accountId) => {
            await receive({ id: recebendo.id, receivedOn, accountId });
          }}
        />
      )}
    </div>
  );
}

/**
 * "Recebi" — a confirmação que transforma renda prevista em caixa (ADR 0034).
 *
 * Pergunta DUAS coisas, e as duas importam: **quando** caiu (é a data que decide
 * em que mês a entrada aparece no caixa) e **em qual conta** (é o que faz o saldo
 * se mexer). A competência não é tocada: o salário de setembro que cai em 2 de
 * outubro continua sendo renda de setembro.
 */
function ConfirmarRecebimentoDialog({
  income,
  contas,
  onClose,
  onConfirm,
}: {
  income: Income;
  contas: { id: number; name: string }[];
  onClose: () => void;
  onConfirm: (receivedOn: string, accountId?: number) => Promise<void>;
}) {
  // O padrão é a data PREVISTA, não hoje: o caso comum é confirmar o que caiu no
  // dia certo, e datar tudo com "hoje" moveria a entrada de mês toda vez que
  // alguém confirmasse com atraso.
  const [quando, setQuando] = React.useState(income.received_at.slice(0, 10));
  const [conta, setConta] = React.useState<number | ''>(
    (income.account_id as number | null) ?? contas[0]?.id ?? '',
  );
  const [salvando, setSalvando] = React.useState(false);

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Confirmar recebimento</DialogTitle>
          <DialogDescription>
            {income.title} — {formatCurrency(parseFloat(income.amount), income.currency ?? 'BRL')}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label htmlFor="receb-data">Recebi em</Label>
            <Input
              id="receb-data" type="date" value={quando}
              onChange={(e) => setQuando(e.target.value)}
            />
            <p className="mt-1 text-xs text-muted-foreground">
              A renda continua sendo do mês de competência — só o caixa usa esta data.
            </p>
          </div>
          {contas.length > 0 && (
            <div>
              <Label htmlFor="receb-conta">Caiu na conta</Label>
              <NativeSelect
                id="receb-conta" value={String(conta)}
                onChange={(e) => setConta(e.target.value ? Number(e.target.value) : '')}
              >
                <option value="">Não informar</option>
                {contas.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </NativeSelect>
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancelar</Button>
          <Button
            pending={salvando}
            onClick={async () => {
              setSalvando(true);
              try {
                await onConfirm(quando, conta === '' ? undefined : conta);
                toast.success('Recebimento confirmado.');
                onClose();
              } catch (err) {
                toast.error(getApiErrorMessage(err, 'Erro ao confirmar o recebimento.'));
              } finally {
                setSalvando(false);
              }
            }}
          >
            Confirmar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
