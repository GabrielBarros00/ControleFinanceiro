import * as React from 'react';
import { useFormContext } from 'react-hook-form';
import { CalendarClock } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { useCreditCards, useStatementTarget } from '@/hooks/use-credit-cards';
import { usePaymentAccounts } from '@/hooks/use-payment-accounts';
import { parseApiDay } from '@/lib/date';
import { formatCurrency } from '@/lib/money';
import { PAYMENT_METHOD_OPTIONS } from '@/lib/payment-methods';
import type { TransactionFormValues } from './schema';

const selectClass =
  'flex h-10 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring';

interface PaymentMethodFieldProps {
  allowInstallments?: boolean;
}

export function PaymentMethodField({ allowInstallments = false }: PaymentMethodFieldProps) {
  const { register, watch, setValue, getValues, trigger, formState: { errors } } = useFormContext<TransactionFormValues>();
  const { cards } = useCreditCards();
  const { activeAccounts } = usePaymentAccounts();
  const paymentMethod = watch('payment_method');
  const creditCardId = watch('credit_card_id');
  const totalAmount = watch('total_amount');
  const transactionDate = watch('transaction_date');
  const singlePayer = (watch('payers') ?? []).length <= 1;

  // Revalida cruzado: escolher o cartão limpa na hora o erro "selecione o cartão"
  // (que pode ter sido disparado pela origem de um pagador). Corrige o caso em
  // que a mensagem ficava presa mesmo após preencher a Forma de pagamento.
  React.useEffect(() => {
    trigger(['credit_card_id', 'payers']);
  }, [creditCardId, trigger]);

  // Trocar de crédito para outro método descarta o cartão — o backend rejeita
  // (com razão) pix/dinheiro com credit_card_id preenchido — e volta à vista
  React.useEffect(() => {
    if (paymentMethod !== 'credit_card') {
      if (getValues('credit_card_id')) setValue('credit_card_id', '');
      if (getValues('installments') > 1) setValue('installments', 1);
    } else if (getValues('payers.0.account_id')) {
      // Crédito não sai de conta: limpa a origem do pagador único
      setValue('payers.0.account_id', '');
    }
  }, [paymentMethod, getValues, setValue]);

  return (
    <div className="space-y-2">
    <div className="grid grid-cols-2 gap-6">
      <div className="space-y-2">
        <Label htmlFor="payment_method" className="text-sm font-semibold text-foreground">Forma de pagamento</Label>
        <select id="payment_method" className={selectClass} {...register('payment_method')}>
          <option value="" className="bg-card">Não informado</option>
          {PAYMENT_METHOD_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value} className="bg-card">{opt.label}</option>
          ))}
        </select>
      </div>
      {paymentMethod && paymentMethod !== 'credit_card' && singlePayer && activeAccounts.length > 0 && (
        <div className="space-y-2">
          <Label htmlFor="payer_account_id" className="text-sm font-semibold text-foreground">
            De qual conta? <span className="font-normal text-muted-foreground">(opcional)</span>
          </Label>
          <select id="payer_account_id" className={selectClass} {...register('payers.0.account_id')}>
            <option value="" className="bg-card">Não informado</option>
            {activeAccounts.map((a) => (
              <option key={a.id} value={a.id} className="bg-card">{a.name}</option>
            ))}
          </select>
        </div>
      )}
      {paymentMethod === 'credit_card' && (
        <div className="space-y-2">
          <Label htmlFor="credit_card_id" className="text-sm font-semibold text-foreground">Qual cartão?</Label>
          <select id="credit_card_id" className={selectClass} {...register('credit_card_id')}>
            <option value="" className="bg-card">Selecione...</option>
            {cards.map((card: { id: number; name: string }) => (
              <option key={card.id} value={card.id} className="bg-card">{card.name}</option>
            ))}
          </select>
          {errors.credit_card_id && (
            <p className="text-xs text-destructive font-medium">{errors.credit_card_id.message as string}</p>
          )}
        </div>
      )}
      {paymentMethod === 'credit_card' && allowInstallments && (
        <div className="space-y-2">
          <Label htmlFor="installments" className="text-sm font-semibold text-foreground">Parcelas</Label>
          <select
            id="installments"
            className={selectClass}
            {...register('installments', { valueAsNumber: true })}
          >
            <option value={1} className="bg-card">À vista</option>
            {Array.from({ length: 23 }, (_, i) => i + 2).map((n) => (
              <option key={n} value={n} className="bg-card">
                {n}x de {formatCurrency((totalAmount || 0) / n)}
              </option>
            ))}
          </select>
          {errors.installments && (
            <p className="text-xs text-destructive font-medium">{errors.installments.message as string}</p>
          )}
        </div>
      )}
    </div>
    <StatementTargetHint cardId={creditCardId} date={transactionDate} />
    </div>
  );
}

/**
 * "Vai para a fatura de Agosto/2026 (vence 10/09)".
 *
 * A fatura é derivada no SERVIDOR (ADR 0002) por uma regra que o formulário não
 * contava: a partir do dia de fechamento a compra vai para o mês SEGUINTE, e se
 * aquela fatura já estiver fechada ela rola para frente. O usuário só descobria
 * o destino depois de salvar — e "por que minha compra de hoje está na fatura de
 * setembro?" não tinha resposta em lugar nenhum da tela.
 */
function StatementTargetHint({
  cardId,
  date,
}: {
  cardId?: string | number | null;
  date?: string | null;
}) {
  const id = cardId ? Number(cardId) : null;
  const { target } = useStatementTarget(id, date || null);
  if (!target) return null;

  // parseApiDay: closing_date/due_date são DIAS de calendário serializados como
  // datetime à meia-noite — parseApiDate os atrasaria em um dia em fuso negativo.
  const vencimento = parseApiDay(target.due_date).toLocaleDateString('pt-BR', {
    day: '2-digit',
    month: '2-digit',
  });

  return (
    <p className="text-xs text-muted-foreground">
      <CalendarClock className="mr-1 inline h-3.5 w-3.5 align-[-2px]" />
      Vai para a fatura de{' '}
      <span className="font-medium text-foreground">{monthLongLabel(target.month)}</span>
      {' '}(vence {vencimento})
      {target.rolled_forward && ' — a fatura do mês da compra já está fechada'}
    </p>
  );
}

function monthLongLabel(month: string): string {
  const [y, m] = month.split('-').map(Number);
  if (!y || !m) return month;
  const rotulo = new Date(y, m - 1, 1).toLocaleDateString('pt-BR', {
    month: 'long',
    year: 'numeric',
  });
  return rotulo.charAt(0).toUpperCase() + rotulo.slice(1);
}
