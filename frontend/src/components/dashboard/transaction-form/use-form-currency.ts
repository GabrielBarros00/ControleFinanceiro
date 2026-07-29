import { useFormContext } from 'react-hook-form';
import { currencySymbol, formatCurrency } from '@/lib/money';
import type { TransactionFormValues } from './schema';

/**
 * Moeda do lançamento sendo editado — a que o usuário escolheu no combobox ao
 * lado do "Valor Total".
 *
 * Existe porque só o campo do total respeitava essa escolha: itens, pagadores,
 * valores fixos e todos os resumos vivos usavam o default "R$" do MoneyInput e
 * o default BRL do formatCurrency. Numa despesa em USD o topo dizia US$ e o
 * resto da MESMA despesa dizia R$ — com os mesmos números.
 */
export function useFormCurrency() {
  const { watch } = useFormContext<TransactionFormValues>();
  const currency = watch('currency') || 'BRL';
  return {
    currency,
    symbol: currencySymbol(currency),
    fmt: (value: number | string) => formatCurrency(value, currency),
  };
}
