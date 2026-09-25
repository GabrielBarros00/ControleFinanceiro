import { useFormContext } from 'react-hook-form';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useMerchants } from '@/hooks/use-merchants';
import type { TransactionFormValues } from './schema';

/**
 * Onde a despesa foi feita (ADR 0038).
 *
 * `<input list>` nativo, e não um combobox: o formulário vive dentro de um
 * Dialog, e o popup do Base UI foge do focus-trap dele. A lista sugere os
 * estabelecimentos do espaço, e um nome novo cria um na hora de salvar.
 */
export function MerchantField() {
  const { register, watch, formState: { errors } } = useFormContext<TransactionFormValues>();
  const { merchants } = useMerchants();
  const inicial = watch('merchant_initial');
  const atual = watch('merchant_name');
  const desvincula = Boolean(inicial) && !atual.trim();

  return (
    <div className="space-y-2">
      <Label htmlFor="merchant_name" className="text-sm font-semibold text-foreground">Estabelecimento</Label>
      <Input
        id="merchant_name"
        list="merchant-sugestoes"
        autoComplete="off"
        placeholder="Onde foi a compra (opcional)"
        {...register('merchant_name')}
        className="bg-background border-border"
      />
      <datalist id="merchant-sugestoes">
        {merchants.map((m) => <option key={m.id} value={m.name} />)}
      </datalist>
      {errors.merchant_name
        ? <p className="text-xs text-destructive font-medium">{errors.merchant_name.message as string}</p>
        : (
          <p className="text-xs text-muted-foreground">
            {desvincula
              ? `Ao salvar, a despesa deixa de ser de ${inicial}.`
              : 'Vazio, uma despesa nova se liga sozinha quando o título é um apelido cadastrado.'}
          </p>
        )}
    </div>
  );
}
