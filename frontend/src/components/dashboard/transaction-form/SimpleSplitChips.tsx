import { useFormContext } from 'react-hook-form';
import { ChipsDeDivisao } from '@/components/money/ChipsDeDivisao';
import { useFormCurrency } from './use-form-currency';
import type { Participant } from './SplitEditor';
import type { TransactionFormValues } from './schema';

interface SimpleSplitChipsProps {
  participants: Participant[];
}

/**
 * Divisão simples (modo padrão): escolha quem participa → rateio IGUAL.
 *
 * Escreve em `splits` com method 'equal'. Controle fino (%/fixo/por item) mora
 * em "Opções avançadas".
 *
 * O DESENHO das pílulas mora em `components/money/ChipsDeDivisao` desde que a
 * recorrência passou a fazer a mesma pergunta — aqui fica só a ligação com o
 * `react-hook-form` deste formulário. Duas telas que perguntam a mesma coisa
 * devem parecer a mesma coisa.
 */
export function SimpleSplitChips({ participants }: SimpleSplitChipsProps) {
  const { watch, setValue } = useFormContext<TransactionFormValues>();
  const { fmt } = useFormCurrency();
  const splits = watch('splits') ?? [];
  const total = watch('total_amount') ?? 0;

  const alternar = (id: string) => {
    const marcado = splits.some((s) => s.user_id === id);
    const proximo = marcado
      ? splits.filter((s) => s.user_id !== id)
      : [...splits, { user_id: id, value: 0 }];
    setValue('splits', proximo, { shouldValidate: true, shouldDirty: true });
  };

  return (
    <ChipsDeDivisao
      participantes={participants}
      selecionados={splits.map((s) => s.user_id)}
      onAlternar={alternar}
      total={total}
      formatar={fmt}
    />
  );
}
