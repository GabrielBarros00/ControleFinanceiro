import type { PaymentMethod } from '@/types/transaction';

export const PAYMENT_METHOD_LABELS: Record<PaymentMethod, string> = {
  credit_card: 'Cartão de crédito',
  debit_card: 'Cartão de débito',
  pix: 'Pix',
  cash: 'Dinheiro',
  bank_transfer: 'Transferência',
  boleto: 'Boleto',
  other: 'Outro',
};

export const PAYMENT_METHOD_OPTIONS = (
  Object.entries(PAYMENT_METHOD_LABELS) as [PaymentMethod, string][]
).map(([value, label]) => ({ value, label }));

// Legado (pré-migração) pode ter payment_method NULL: infere pelo cartão
export function paymentMethodLabel(
  method: string | null | undefined,
  creditCardId?: number | null
): string {
  if (method && method in PAYMENT_METHOD_LABELS) {
    return PAYMENT_METHOD_LABELS[method as PaymentMethod];
  }
  return creditCardId ? PAYMENT_METHOD_LABELS.credit_card : '—';
}
