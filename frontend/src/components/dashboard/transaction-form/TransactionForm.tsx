import * as React from 'react';
import { useForm, FormProvider, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/MoneyInput';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { CheckCircle2, AlertCircle, SlidersHorizontal, ChevronDown } from 'lucide-react';
import { useMembers } from '@/hooks/use-members';
import { useCategories } from '@/hooks/use-categories';
import { useExchangeRate } from '@/hooks/use-exchange-rate';
import { useBaseCurrency } from '@/hooks/use-base-currency';
import { useAuthStore } from '@/stores';
import { cn } from '@/lib/utils';
import { currencySymbol, formatMoney } from '@/lib/money';
import { getApiErrorMessage } from '@/lib/api-error';
import {
  transactionFormSchema,
  toApiPayload,
  todayLocalISO,
  type TransactionFormValues,
} from './schema';
import { useSettlementTracking } from '@/hooks/use-settlement-tracking';
import { SplitEditor } from './SplitEditor';
import { ItemsEditor } from './ItemsEditor';
import { PaymentMethodField } from './PaymentMethodField';
import { PayersEditor } from './PayersEditor';
import { TagMultiSelect } from './TagMultiSelect';
import { SimpleSplitChips } from './SimpleSplitChips';
import { CurrencyCombobox } from './CurrencyCombobox';
import { nativeSelectClass as selectClass } from '@/components/ui/native-select';

export type TransactionApiPayload = ReturnType<typeof toApiPayload>;

interface TransactionFormProps {
  initialValues: TransactionFormValues;
  onSubmit: (payload: TransactionApiPayload) => Promise<void>;
  submitLabel: string;
  resetOnSuccess?: boolean;
  allowInstallments?: boolean;
  // Chamado após um submit bem-sucedido (ex.: fechar o modal)
  onSuccess?: () => void;
  // Bloco extra dentro do form, acima do botão de salvar (ex.: anexos na criação)
  extraFields?: React.ReactNode;
}

// Form compartilhado criar/editar despesa. Layout slim: o essencial fica sempre
// visível; método %/fixo, divisão por item e categoria moram em "Opções
// avançadas" (progressive disclosure).
export function TransactionForm({ initialValues, onSubmit, submitLabel, resetOnSuccess = false, allowInstallments = false, onSuccess, extraFields }: TransactionFormProps) {
  const { user } = useAuthStore();
  const { members } = useMembers();
  const { categories } = useCategories();
  const [loading, setLoading] = React.useState(false);
  const [success, setSuccess] = React.useState(false);
  const [apiError, setApiError] = React.useState<string | null>(null);

  // Abre "avançado" já aberto quando os valores iniciais não são o caso simples
  // (edição de despesa em %/fixo ou por item)
  const [advanced, setAdvanced] = React.useState(
    () => initialValues.split_mode === 'item' || initialValues.split_method !== 'equal'
  );

  // Participantes reais do workspace (fallback: usuário atual enquanto carrega)
  const participants = members.length > 0
    ? members.map((m) => ({ id: String(m.user_id), name: m.user_name }))
    : user ? [{ id: String(user.id), name: user.name }] : [];

  const methods = useForm({
    resolver: zodResolver(transactionFormSchema),
    mode: 'onChange',
    defaultValues: initialValues,
  });
  const { register, control, handleSubmit, watch, reset, getValues, setValue, trigger, formState: { errors } } = methods;

  const splitMode = watch('split_mode');
  const currency = watch('currency');
  const baseCurrency = useBaseCurrency();
  const controlaPagamento = useSettlementTracking();
  const paymentMethod = watch('payment_method');
  const settled = watch('settled');
  const transactionDate = watch('transaction_date');
  const defaultUserId = user ? String(user.id) : '';

  // "Já foi paga" acompanha a DATA quando ela muda: ninguém pagou o boleto que
  // vence semana que vem (ADR 0029). A comparação é de strings `YYYY-MM-DD`, que
  // ordenam lexicograficamente e não passam por fuso nenhum.
  //
  // Só no CHANGE, nunca na montagem — daí o `ref`. Ao abrir uma despesa para
  // editar, o formulário carrega o estado real da liquidação; recalcular pela
  // data ali marcaria como paga toda conta em aberto com vencimento passado,
  // que é exatamente a fila de Contas a pagar.
  const dataAnterior = React.useRef(transactionDate);
  React.useEffect(() => {
    if (dataAnterior.current === transactionDate) return;
    dataAnterior.current = transactionDate;
    setValue('settled', transactionDate <= todayLocalISO(), { shouldValidate: false });
  }, [transactionDate, setValue]);

  const handleSplitModeChange = (mode: 'transaction' | 'item') => {
    setValue('split_mode', mode, { shouldValidate: true });
    if (mode === 'item' && getValues('items').length === 0) {
      setValue('items', [{
        title: '',
        quantity: 1,
        unit_amount: null,
        amount: 0,
        category_id: '',
        share_method: 'equal',
        shares: defaultUserId ? [{ user_id: defaultUserId, value: 0 }] : [],
      }]);
    }
    if (mode === 'transaction' && getValues('splits').length === 0) {
      setValue('splits', defaultUserId ? [{ user_id: defaultUserId, value: 0 }] : []);
    }
  };

  const toggleAdvanced = () => {
    setAdvanced((prev) => {
      const next = !prev;
      // Ao recolher, volta ao caso simples: divisão igual pela despesa
      if (!next) {
        if (getValues('split_mode') !== 'transaction') setValue('split_mode', 'transaction', { shouldValidate: true });
        if (getValues('split_method') !== 'equal') setValue('split_method', 'equal', { shouldValidate: true });
        if ((getValues('splits') ?? []).length === 0 && defaultUserId) {
          setValue('splits', [{ user_id: defaultUserId, value: 0 }], { shouldValidate: true });
        }
      }
      return next;
    });
  };

  const submit = async (data: unknown) => {
    const values = data as TransactionFormValues;
    setLoading(true);
    setApiError(null);
    try {
      await onSubmit(toApiPayload(values));
      if (resetOnSuccess) {
        reset();
        setSuccess(true);
        setTimeout(() => setSuccess(false), 3000);
      }
      onSuccess?.();
    } catch (err) {
      setApiError(getApiErrorMessage(err, 'Erro ao salvar despesa. Verifique os campos.'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <FormProvider {...methods}>
      <form onSubmit={handleSubmit(submit)}>
        <div className="space-y-5">

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="title" className="text-sm font-semibold text-foreground">Título / Descrição</Label>
              <Input id="title" placeholder="Ex: Mercado" {...register('title')} className="bg-background border-border focus:ring-primary" />
              {errors.title && <p className="text-xs text-destructive font-medium">{errors.title.message as string}</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="total_amount" className="text-sm font-semibold text-foreground">Valor Total</Label>
              <div className="flex gap-2">
                <Controller
                  name="total_amount"
                  control={control}
                  render={({ field }) => (
                    <MoneyInput
                      id="total_amount"
                      value={field.value}
                      onChange={field.onChange}
                      prefix={currencySymbol(currency)}
                      className="bg-background border-border focus:ring-primary font-bold flex-1"
                    />
                  )}
                />
                <CurrencyCombobox
                  value={currency}
                  onChange={(c) => {
                    setValue('currency', c, { shouldValidate: true });
                    // Revalida o form INTEIRO: as mensagens de soma citam valores
                    // formatados na moeda, e com `shouldValidate` só o campo
                    // `currency` era revisitado — os erros de itens/pagadores
                    // ficavam congelados na moeda anterior ("R$" numa despesa
                    // que já era USD).
                    void trigger();
                  }}
                />
              </div>
              {errors.total_amount && <p className="text-xs text-destructive font-medium">{errors.total_amount.message as string}</p>}
              {/* "Estrangeira" é != da moeda-BASE do espaço, não != 'BRL':
                  num workspace em USD a dica aparecia para toda despesa em
                  dólar (que é a moeda da casa) e sumia para uma em real. */}
              {currency && currency !== baseCurrency && (
                <CurrencyHint currency={currency} amount={watch('total_amount')} />
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <PayersEditor participants={participants} />
            <div className="space-y-2">
              <Label htmlFor="transaction_date" className="text-sm font-semibold text-foreground">Data</Label>
              <Input id="transaction_date" type="date" {...register('transaction_date')} className="bg-background border-border" />
              {errors.transaction_date && <p className="text-xs text-destructive font-medium">{errors.transaction_date.message as string}</p>}
            </div>
          </div>

          <PaymentMethodField allowInstallments={allowInstallments} />

          {/* "Já foi paga" (ADR 0029) — CAIXA, não competência.
              Some no cartão: quem paga a compra é a FATURA, e marcá-la como
              paga aqui somaria a mesma saída duas vezes. Some também nos espaços
              sem controle de pagamento, onde a resposta é sempre "sim". */}
          {controlaPagamento && paymentMethod !== 'credit_card' && (
            <label
              htmlFor="settled"
              className="flex cursor-pointer items-start gap-3 rounded-lg border border-border bg-accent/20 p-3"
            >
              <input
                id="settled"
                type="checkbox"
                {...register('settled')}
                className="mt-0.5 h-5 w-5 shrink-0 rounded border-border accent-primary"
              />
              <span className="min-w-0">
                <span className="block text-sm font-medium text-foreground">Já foi paga</span>
                <span className="block text-xs text-muted-foreground">
                  {settled
                    ? 'O valor sai do seu caixa na data acima.'
                    : 'Fica em Contas a pagar até você confirmar o pagamento.'}
                </span>
              </span>
            </label>
          )}

          <TagMultiSelect />

          {/* Divisão simples (padrão): rateio igual entre os selecionados */}
          {!advanced && <SimpleSplitChips participants={participants} />}

          <div>
            <button
              type="button"
              onClick={toggleAdvanced}
              aria-expanded={advanced}
              className="flex items-center gap-2 text-sm font-semibold text-primary transition-colors hover:text-primary/80"
            >
              <SlidersHorizontal className="h-4 w-4" />
              Opções avançadas
              <ChevronDown className={cn('h-4 w-4 transition-transform', advanced && 'rotate-180')} />
            </button>
          </div>

          {advanced && (
            <div className="space-y-5 rounded-xl border border-border/60 bg-accent/20 p-4 animate-in fade-in slide-in-from-top-1 duration-200">
              <div className="space-y-3">
                <Label className="text-sm font-bold text-foreground">Como dividir?</Label>
                <RadioGroup
                  value={splitMode}
                  onValueChange={(value) => handleSplitModeChange(value as 'transaction' | 'item')}
                  className="flex space-x-6"
                >
                  <div className="flex items-center space-x-2">
                    <RadioGroupItem value="transaction" id="mode-transaction" className="border-primary text-primary" />
                    <Label htmlFor="mode-transaction" className="text-sm font-medium text-foreground cursor-pointer">Pela despesa</Label>
                  </div>
                  <div className="flex items-center space-x-2">
                    <RadioGroupItem value="item" id="mode-item" className="border-primary text-primary" />
                    <Label htmlFor="mode-item" className="text-sm font-medium text-foreground cursor-pointer">Por item</Label>
                  </div>
                </RadioGroup>
              </div>

              {splitMode === 'transaction' && (
                <div className="space-y-2">
                  <Label htmlFor="category_id" className="text-sm font-semibold text-foreground">Categoria</Label>
                  <select id="category_id" className={selectClass} {...register('category_id')}>
                    <option value="" className="bg-card">Sem categoria</option>
                    {categories.map(c => (
                      <option key={c.id} value={c.id} className="bg-card">{c.name}</option>
                    ))}
                  </select>
                </div>
              )}

              {splitMode === 'transaction'
                ? <SplitEditor participants={participants} />
                : <ItemsEditor participants={participants} defaultUserId={defaultUserId} />}
            </div>
          )}

          {extraFields}

        </div>

        {/* `flex-wrap`: a mensagem de erro tem `mr-auto` e nenhum limite de
            largura; ao lado de um botão de 140px fixos, um erro longo empurrava
            o rodapé para fora da tela em vez de quebrar linha. */}
        <div className="mt-6 flex flex-wrap items-center justify-end gap-4 border-t border-border pt-6">
          {apiError && (
            <div role="alert" className="flex min-w-0 flex-1 items-center gap-2 text-destructive text-sm font-medium animate-in fade-in sm:mr-auto">
              <AlertCircle className="h-4 w-4 shrink-0" /> {apiError}
            </div>
          )}
          {success && (
            <div className="flex items-center gap-2 text-emerald-500 text-sm font-bold animate-in fade-in slide-in-from-right-2">
              <CheckCircle2 className="h-4 w-4" /> Salvo com sucesso!
            </div>
          )}
          <Button type="submit" className="h-11 w-full bg-primary px-8 font-bold text-primary-foreground shadow-lg shadow-primary/20 hover:bg-primary/90 sm:h-9 sm:w-auto sm:min-w-[140px]" pending={loading}>
            {submitLabel}
          </Button>
        </div>
      </form>
    </FormProvider>
  );
}

// Referência para moeda estrangeira: mostra a estimativa na MOEDA-BASE do
// workspace (best-effort) e lembra do IOF no cartão. O valor final é congelado
// no servidor na criação — e o hook consulta a mesma taxa cruzada que o servidor
// vai aplicar, então a estimativa não contradiz o valor gravado.
function CurrencyHint({ currency, amount }: { currency: string; amount: number }) {
  const baseCurrency = useBaseCurrency();
  const { rate } = useExchangeRate(currency);
  return (
    <p className="text-[11px] font-medium text-muted-foreground">
      {rate ? `≈ ${formatMoney((amount || 0) * rate, { currency: baseCurrency })} (câmbio ${rate.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}) · ` : ''}
      convertido para {baseCurrency} na entrada (+3,5% de IOF no cartão).
    </p>
  );
}
