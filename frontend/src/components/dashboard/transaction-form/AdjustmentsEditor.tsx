import { useFormContext, useFieldArray, Controller } from 'react-hook-form';
import { Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { MoneyInput } from '@/components/ui/MoneyInput';
import { nativeSelectClass as selectClass } from '@/components/ui/native-select';
import { AJUSTE_ROTULO, TIPOS_DE_AJUSTE, ajusteComSinal, sinalLivre } from '@/lib/ajuste-da-nota';
import { useFormCurrency } from './use-form-currency';
import type { TransactionFormValues } from './schema';

/*
 * Os ajustes da nota: desconto, frete, taxa… — o que leva a soma dos itens ao
 * total pago.
 *
 * A tela só os mostrava no resumo, e nenhuma edição os levava de volta: a IA
 * lançava a nota do delivery com o desconto e a taxa de entrega, e salvar a
 * edição (até para trocar o título) os apagava, porque a edição é completa e
 * ajuste que não vai é ajuste descartado.
 */
export function AdjustmentsEditor() {
  const { control, formState: { errors } } = useFormContext<TransactionFormValues>();
  const { fields, append, remove } = useFieldArray({ control, name: 'adjustments' });

  const erro = errors.adjustments?.root?.message
    ?? (errors.adjustments as { message?: string } | undefined)?.message;

  return (
    <div className="space-y-3" data-testid="adjustments-editor">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-0.5">
          <Label className="text-sm font-bold text-foreground">Ajustes da nota</Label>
          <p className="text-xs text-muted-foreground">
            Desconto, frete, taxa… o que leva a soma dos itens ao total pago.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => append({ type: 'discount', description: '', amount: 0, reduz: true })}
          className="h-8 shrink-0 gap-1 border-primary text-primary hover:bg-primary/10"
        >
          <Plus className="h-3 w-3" /> Ajuste
        </Button>
      </div>

      {fields.map((field, index) => (
        <AjusteRow key={field.id} index={index} onRemove={() => remove(index)} />
      ))}

      {erro && <p className="text-sm font-medium text-destructive">{erro}</p>}
    </div>
  );
}

function AjusteRow({ index, onRemove }: { index: number; onRemove: () => void }) {
  const { register, control, watch, formState: { errors } } = useFormContext<TransactionFormValues>();
  const { symbol } = useFormCurrency();
  const tipo = watch(`adjustments.${index}.type` as const);
  const reduz = watch(`adjustments.${index}.reduz` as const);
  const livre = sinalLivre(tipo);
  // O sinal que vai valer, à vista no próprio campo: "−R$" no desconto.
  const reduzOTotal = ajusteComSinal(tipo, 1, reduz) < 0;
  const erros = errors.adjustments?.[index];

  return (
    <div className="space-y-2 rounded-lg border border-border/50 bg-accent/10 p-3" data-testid={`adjustment-row-${index}`}>
      <div className="flex items-end gap-2">
        <div className="grid flex-1 grid-cols-2 items-start gap-2">
          <div className="min-w-0 space-y-1">
            <Label className="text-[11px] font-semibold text-muted-foreground">Tipo</Label>
            <select aria-label="Tipo do ajuste" className={selectClass} {...register(`adjustments.${index}.type` as const)}>
              {TIPOS_DE_AJUSTE.map((t) => (
                <option key={t} value={t} className="bg-card">{AJUSTE_ROTULO[t]}</option>
              ))}
            </select>
          </div>
          <div className="min-w-0 space-y-1">
            <Label className="text-[11px] font-semibold text-muted-foreground">Valor</Label>
            <Controller
              name={`adjustments.${index}.amount` as const}
              control={control}
              render={({ field }) => (
                <MoneyInput
                  aria-label="Valor do ajuste"
                  value={field.value}
                  onChange={field.onChange}
                  prefix={`${reduzOTotal ? '−' : '+'}${symbol}`}
                  className="bg-background border-border font-bold"
                />
              )}
            />
          </div>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-label="Remover ajuste"
          onClick={onRemove}
          className="h-9 w-9 p-0 text-destructive hover:bg-destructive/10"
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>
      {erros?.amount && <p className="text-[11px] font-medium text-destructive">{erros.amount.message as string}</p>}

      {/* Arredondamento e "outro" vão para qualquer lado: só aqui a pessoa diz. */}
      {livre && (
        <Controller
          name={`adjustments.${index}.reduz` as const}
          control={control}
          render={({ field }) => (
            <select
              aria-label="Sentido do ajuste"
              className={selectClass}
              value={field.value ? 'reduz' : 'aumenta'}
              onChange={(e) => field.onChange(e.target.value === 'reduz')}
            >
              <option value="aumenta" className="bg-card">Acrescenta ao total</option>
              <option value="reduz" className="bg-card">Desconta do total</option>
            </select>
          )}
        />
      )}

      <Input
        aria-label="Descrição do ajuste"
        placeholder="Ex.: cupom, taxa de entrega (opcional)"
        {...register(`adjustments.${index}.description` as const)}
        className="bg-background border-border"
      />
      {erros?.description && <p className="text-[11px] font-medium text-destructive">{erros.description.message as string}</p>}
    </div>
  );
}
