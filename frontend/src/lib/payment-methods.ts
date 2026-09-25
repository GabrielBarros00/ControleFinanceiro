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

/**
 * A forma de pagamento dizendo QUAL cartão: "Cartão Nubank".
 *
 * Sem o nome, uma compra no cartão aparecia só como "Cartão de crédito" — e quem
 * tem mais de um cartão não tinha como saber em qual ela caiu sem abrir a
 * edição, o que levou a achar que o cartão não tinha sido gravado. O nome vem dos
 * cartões da PRÓPRIA pessoa (`cartoes`): o cartão de outro membro do espaço é
 * pessoal dele (ADR 0021) e continua como "Cartão de crédito".
 */
export function paymentMethodWithCard(
  method: string | null | undefined,
  creditCardId: number | null | undefined,
  cartoes: ReadonlyArray<{ id: number; name: string }> | undefined,
): string {
  const nome = creditCardId != null ? cartoes?.find((c) => c.id === creditCardId)?.name : undefined;
  return nome ? `Cartão ${nome}` : paymentMethodLabel(method, creditCardId);
}
