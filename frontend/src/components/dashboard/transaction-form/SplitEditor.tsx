import { useFormContext, useFieldArray, Controller } from 'react-hook-form';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/MoneyInput';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Trash2 } from 'lucide-react';
import { SplitSummary } from './SplitSummary';
import type { TransactionFormValues } from './schema';

export interface Participant {
  id: string;
  name: string;
}

interface SplitEditorProps {
  participants: Participant[];
}

// Divisão no nível da despesa: método único (igual/%/fixo) + participantes
export function SplitEditor({ participants }: SplitEditorProps) {
  const { register, control, watch, formState: { errors } } = useFormContext<TransactionFormValues>();
  const { fields, append, remove } = useFieldArray({ control, name: 'splits' });

  const splitMethod = watch('split_method');
  const watchedSplits = watch('splits');
  const watchedTotal = watch('total_amount');

  const splitsError = errors.splits?.root?.message
    ?? (errors.splits as { message?: string } | undefined)?.message;

  return (
    <>
      <div className="space-y-4 p-4 rounded-xl bg-accent/30 border border-border/50">
        <Label className="text-sm font-bold text-foreground">Método de Divisão</Label>
        <Controller
          name="split_method"
          control={control}
          render={({ field }) => (
            <RadioGroup
              value={field.value}
              onValueChange={(value) => field.onChange(value as string)}
              className="flex space-x-6"
            >
              <div className="flex items-center space-x-2">
                <RadioGroupItem value="equal" id="equal" className="border-primary text-primary" />
                <Label htmlFor="equal" className="text-sm font-medium text-foreground cursor-pointer">Igual</Label>
              </div>
              <div className="flex items-center space-x-2">
                <RadioGroupItem value="percentage" id="percentage" className="border-primary text-primary" />
                <Label htmlFor="percentage" className="text-sm font-medium text-foreground cursor-pointer">Porcentagem</Label>
              </div>
              <div className="flex items-center space-x-2">
                <RadioGroupItem value="fixed" id="fixed" className="border-primary text-primary" />
                <Label htmlFor="fixed" className="text-sm font-medium text-foreground cursor-pointer">Valor Fixo</Label>
              </div>
            </RadioGroup>
          )}
        />
      </div>

      <div className="space-y-4 border-t border-border pt-6">
        <div className="flex items-center justify-between">
          <Label className="text-sm font-bold text-foreground">Divisões (Splits)</Label>
          <Button type="button" variant="outline" size="sm" onClick={() => append({ user_id: '', value: 0 })} className="h-8 border-primary text-primary hover:bg-primary/10">
            + Participante
          </Button>
        </div>
        <div className="space-y-3">
          {fields.map((field, index) => (
            <div key={field.id} className="flex items-center gap-3 animate-in slide-in-from-left-2 duration-200">
              <div className="flex-1">
                <select
                  aria-label="Participante"
                  className="flex h-9 w-full rounded-md border border-border bg-background px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary text-foreground"
                  {...register(`splits.${index}.user_id` as const)}
                >
                  <option value="" className="bg-card">Usuário...</option>
                  {participants.map(p => (
                    <option key={p.id} value={p.id} className="bg-card">{p.name}</option>
                  ))}
                </select>
                {errors.splits?.[index]?.user_id && <p className="text-[10px] text-destructive mt-1 font-medium">{errors.splits[index]?.user_id?.message as string}</p>}
              </div>

              {splitMethod !== 'equal' && (
                <div className="w-28">
                  {splitMethod === 'percentage' ? (
                    <Input
                      type="number"
                      step="0.01"
                      placeholder="%"
                      aria-label="Percentual"
                      {...register(`splits.${index}.value` as const, { valueAsNumber: true })}
                      className="bg-background border-border"
                    />
                  ) : (
                    <Controller
                      name={`splits.${index}.value` as const}
                      control={control}
                      render={({ field }) => (
                        <MoneyInput
                          aria-label="Valor fixo"
                          value={field.value}
                          onChange={field.onChange}
                          className="bg-background border-border"
                        />
                      )}
                    />
                  )}
                  {errors.splits?.[index]?.value && <p className="text-[10px] text-destructive mt-1 font-medium">{errors.splits[index]?.value?.message as string}</p>}
                </div>
              )}

              <Button type="button" variant="ghost" size="sm" aria-label="Remover participante" onClick={() => remove(index)} className="h-9 w-9 p-0 text-destructive hover:bg-destructive/10">
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          ))}
        </div>
        <SplitSummary method={splitMethod} splits={watchedSplits ?? []} totalAmount={watchedTotal ?? 0} />
        {splitsError && <p className="text-sm text-destructive font-medium">{splitsError}</p>}
      </div>
    </>
  );
}
