import * as React from 'react';
import { useForm, FormProvider, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/MoneyInput';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Loader2, CheckCircle2, AlertCircle } from 'lucide-react';
import { useMembers } from '@/hooks/use-members';
import { useCategories } from '@/hooks/use-categories';
import { useAuthStore } from '@/stores';
import { getApiErrorMessage } from '@/lib/api-error';
import {
  transactionFormSchema,
  toApiPayload,
  type TransactionFormValues,
} from './schema';
import { SplitEditor } from './SplitEditor';
import { ItemsEditor } from './ItemsEditor';
import { PaymentMethodField } from './PaymentMethodField';
import { PayersEditor } from './PayersEditor';
import { TagsField } from './TagsField';

const selectClass =
  'flex h-10 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring';

export type TransactionApiPayload = ReturnType<typeof toApiPayload>;

interface TransactionFormProps {
  initialValues: TransactionFormValues;
  onSubmit: (payload: TransactionApiPayload) => Promise<void>;
  submitLabel: string;
  resetOnSuccess?: boolean;
  allowInstallments?: boolean;
}

// Form compartilhado criar/editar despesa: campos base + forma de pagamento +
// divisão pela despesa (SplitEditor) OU por item (ItemsEditor)
export function TransactionForm({ initialValues, onSubmit, submitLabel, resetOnSuccess = false, allowInstallments = false }: TransactionFormProps) {
  const { user } = useAuthStore();
  const { members } = useMembers();
  const { categories } = useCategories();
  const [loading, setLoading] = React.useState(false);
  const [success, setSuccess] = React.useState(false);
  const [apiError, setApiError] = React.useState<string | null>(null);

  // Participantes reais do workspace (fallback: usuário atual enquanto carrega)
  const participants = members.length > 0
    ? members.map((m) => ({ id: String(m.user_id), name: m.user_name }))
    : user ? [{ id: String(user.id), name: user.name }] : [];

  const methods = useForm({
    resolver: zodResolver(transactionFormSchema),
    mode: 'onChange',
    defaultValues: initialValues,
  });
  const { register, control, handleSubmit, watch, reset, getValues, setValue, formState: { errors } } = methods;

  const splitMode = watch('split_mode');
  const defaultUserId = user ? String(user.id) : '';

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
    } catch (err) {
      setApiError(getApiErrorMessage(err, 'Erro ao salvar despesa. Verifique os campos.'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <FormProvider {...methods}>
      <form onSubmit={handleSubmit(submit)}>
        <div className="space-y-6">

          <div className="grid grid-cols-2 gap-6">
            <div className="space-y-2">
              <Label htmlFor="title" className="text-sm font-semibold text-foreground">Título / Descrição</Label>
              <Input id="title" placeholder="Ex: Mercado" {...register('title')} className="bg-background border-border focus:ring-primary" />
              {errors.title && <p className="text-xs text-destructive font-medium">{errors.title.message as string}</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="total_amount" className="text-sm font-semibold text-foreground">Valor Total</Label>
              <Controller
                name="total_amount"
                control={control}
                render={({ field }) => (
                  <MoneyInput
                    id="total_amount"
                    value={field.value}
                    onChange={field.onChange}
                    className="bg-background border-border focus:ring-primary font-bold"
                  />
                )}
              />
              {errors.total_amount && <p className="text-xs text-destructive font-medium">{errors.total_amount.message as string}</p>}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-6">
            <PayersEditor participants={participants} />
            <div className="space-y-2">
              <Label htmlFor="transaction_date" className="text-sm font-semibold text-foreground">Data</Label>
              <Input id="transaction_date" type="date" {...register('transaction_date')} className="bg-background border-border" />
              {errors.transaction_date && <p className="text-xs text-destructive font-medium">{errors.transaction_date.message as string}</p>}
            </div>
          </div>

          <PaymentMethodField allowInstallments={allowInstallments} />

          <TagsField />

          {splitMode === 'transaction' && (
            <div className="grid grid-cols-2 gap-6">
              <div className="space-y-2">
                <Label htmlFor="category_id" className="text-sm font-semibold text-foreground">Categoria</Label>
                <select id="category_id" className={selectClass} {...register('category_id')}>
                  <option value="" className="bg-card">Sem categoria</option>
                  {categories.map(c => (
                    <option key={c.id} value={c.id} className="bg-card">{c.name}</option>
                  ))}
                </select>
              </div>
            </div>
          )}

          <div className="space-y-3 p-4 rounded-xl bg-accent/30 border border-border/50">
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

          {splitMode === 'transaction'
            ? <SplitEditor participants={participants} />
            : <ItemsEditor participants={participants} defaultUserId={defaultUserId} />}

        </div>

        <div className="flex justify-end border-t border-border mt-6 pt-6 gap-4 items-center">
          {apiError && (
            <div role="alert" className="flex items-center gap-2 text-destructive text-sm font-medium animate-in fade-in mr-auto">
              <AlertCircle className="h-4 w-4 shrink-0" /> {apiError}
            </div>
          )}
          {success && (
            <div className="flex items-center gap-2 text-emerald-500 text-sm font-bold animate-in fade-in slide-in-from-right-2">
              <CheckCircle2 className="h-4 w-4" /> Salvo com sucesso!
            </div>
          )}
          <Button type="submit" className="bg-primary hover:bg-primary/90 text-primary-foreground font-bold px-8 shadow-lg shadow-primary/20 min-w-[140px]" disabled={loading}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : submitLabel}
          </Button>
        </div>
      </form>
    </FormProvider>
  );
}
