import { useFormContext, useFieldArray, Controller } from 'react-hook-form';
import { Button } from '@/components/ui/button';
import { MoneyInput } from '@/components/ui/MoneyInput';
import { Label } from '@/components/ui/label';
import { Trash2 } from 'lucide-react';
import { PAYMENT_METHOD_OPTIONS } from '@/lib/payment-methods';
import { usePaymentAccounts } from '@/hooks/use-payment-accounts';
import { useFormCurrency } from './use-form-currency';
import type { Participant } from './SplitEditor';
import type { TransactionFormValues } from './schema';
import { nativeSelectClass as selectClass } from '@/components/ui/native-select';

interface PayersEditorProps {
  participants: Participant[];
}

// Quem pagou: um pagador (valor = total, implícito) ou vários com soma == total
export function PayersEditor({ participants }: PayersEditorProps) {
  const { register, control, watch, formState: { errors } } = useFormContext<TransactionFormValues>();
  const { fields, append, remove } = useFieldArray({ control, name: 'payers' });
  const { activeAccounts } = usePaymentAccounts();
  const { symbol, fmt } = useFormCurrency();

  const watchedPayers = watch('payers');
  const watchedTotal = watch('total_amount');
  const creditCardId = watch('credit_card_id');
  const multi = fields.length > 1;

  const payersError = errors.payers?.root?.message
    ?? (errors.payers as { message?: string } | undefined)?.message;

  const sumCents = (watchedPayers ?? []).reduce(
    (acc, p) => acc + Math.round((Number.isFinite(p?.amount) ? p.amount : 0) * 100), 0
  );
  const totalCents = Math.round((watchedTotal ?? 0) * 100);
  const closed = totalCents > 0 && sumCents === totalCents;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Label htmlFor="payer-0" className="text-sm font-semibold text-foreground">Quem pagou?</Label>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => append({ user_id: '', amount: 0, payment_method: '', account_id: '' })}
          className="h-7 text-xs text-primary hover:bg-primary/10"
        >
          + Pagador
        </Button>
      </div>
      <div className="space-y-2">
        {fields.map((field, index) => (
          <div key={field.id} className="space-y-1">
            <div className="flex items-center gap-3">
              <div className="flex-1">
                <select
                  id={index === 0 ? 'payer-0' : undefined}
                  aria-label={index === 0 ? undefined : 'Pagador'}
                  className={selectClass}
                  {...register(`payers.${index}.user_id` as const)}
                >
                  <option value="" className="bg-card">Selecione...</option>
                  {participants.map(p => (
                    <option key={p.id} value={p.id} className="bg-card">{p.name}</option>
                  ))}
                </select>
                {errors.payers?.[index]?.user_id && (
                  <p className="text-[10px] text-destructive mt-1 font-medium">{errors.payers[index]?.user_id?.message as string}</p>
                )}
              </div>
              {multi && (
                // `min-w` + `flex-1` no lugar de `w-32`: o MoneyInput reserva
                // ~48px para o prefixo da moeda e a borda, então 128px fixos
                // deixavam 80px de dígitos — um valor de milhar já não cabia.
                <div className="min-w-28 flex-1 sm:max-w-40">
                  <Controller
                    name={`payers.${index}.amount` as const}
                    control={control}
                    render={({ field }) => (
                      <MoneyInput
                        aria-label="Valor pago"
                        value={field.value}
                        onChange={field.onChange}
                        prefix={symbol}
                        className="bg-background border-border"
                      />
                    )}
                  />
                </div>
              )}
              {multi && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  aria-label="Remover pagador"
                  onClick={() => remove(index)}
                  className="h-9 w-9 p-0 text-destructive hover:bg-destructive/10"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              )}
            </div>
            {multi && (
              // Origem por pagador (ADR 0004): cada um pode ter método/conta próprios
              <div className="flex items-center gap-3 pl-1">
                <select
                  aria-label="Método do pagador"
                  // `text-base md:text-xs`: no celular a fonte NÃO pode descer
                  // de 16px — o Safari do iPhone dá zoom ao focar e não desfaz.
                  // A densidade que o `text-xs` buscava fica valendo só no
                  // desktop, onde a linha de pagador é secundária.
                  className={`${selectClass} h-9 flex-1 text-base md:text-xs`}
                  {...register(`payers.${index}.payment_method` as const)}
                >
                  <option value="" className="bg-card">Método da despesa</option>
                  {PAYMENT_METHOD_OPTIONS.map((opt) => {
                    // Crédito por pagador exige o cartão da despesa definido —
                    // desabilita a opção enquanto não houver, evitando o estado
                    // inválido que travava a mensagem de erro
                    const needsCard = opt.value === 'credit_card' && !creditCardId;
                    return (
                      <option key={opt.value} value={opt.value} className="bg-card" disabled={needsCard}>
                        {opt.label}{needsCard ? ' — defina o cartão da despesa' : ''}
                      </option>
                    );
                  })}
                </select>
                {watchedPayers?.[index]?.payment_method !== 'credit_card' && activeAccounts.length > 0 && (
                  <select
                    aria-label="Conta do pagador"
                    className={`${selectClass} h-9 flex-1 text-base md:text-xs`}
                    {...register(`payers.${index}.account_id` as const)}
                  >
                    <option value="" className="bg-card">Sem conta</option>
                    {activeAccounts.map((a) => (
                      <option key={a.id} value={a.id} className="bg-card">{a.name}</option>
                    ))}
                  </select>
                )}
              </div>
            )}
            {errors.payers?.[index]?.payment_method && (
              <p className="text-[10px] text-destructive font-medium">{errors.payers[index]?.payment_method?.message as string}</p>
            )}
            {errors.payers?.[index]?.account_id && (
              <p className="text-[10px] text-destructive font-medium">{errors.payers[index]?.account_id?.message as string}</p>
            )}
          </div>
        ))}
      </div>
      {multi && (
        <p
          data-testid="payers-summary"
          className={`text-xs font-semibold ${closed ? 'text-income' : 'text-warning'}`}
        >
          {closed
            ? `Pagadores fecham ${fmt(watchedTotal ?? 0)}`
            : `Pagadores: ${fmt(sumCents / 100)} de ${fmt(totalCents / 100)}`}
        </p>
      )}
      {payersError && <p className="text-xs text-destructive font-medium">{payersError}</p>}
    </div>
  );
}
