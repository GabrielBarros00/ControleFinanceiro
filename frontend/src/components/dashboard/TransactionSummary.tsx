import { CreditCard, Landmark, Receipt, Users } from 'lucide-react';
import { useMembers } from '@/hooks/use-members';
import { usePaymentAccounts } from '@/hooks/use-payment-accounts';
import { paymentMethodLabel } from '@/lib/payment-methods';
import { formatCurrency } from '@/lib/money';
import type { AdjustmentType, TransactionRead } from '@/types/transaction';

const ADJUSTMENT_TYPE_LABELS: Record<AdjustmentType, string> = {
  discount: 'Desconto',
  tax: 'Taxa/Imposto',
  tip: 'Gorjeta',
  shipping: 'Frete',
  cashback: 'Cashback',
  rounding: 'Arredondamento',
  other: 'Ajuste',
};

interface TransactionSummaryProps {
  transaction: TransactionRead;
}

// Detalhe de leitura da despesa: quem pagou (e DE ONDE saiu o dinheiro),
// como ficou dividida, ajustes do documento e parcela — o form logo abaixo
// continua sendo o lugar de editar.
export function TransactionSummary({ transaction }: TransactionSummaryProps) {
  const { members } = useMembers();
  const { accounts } = usePaymentAccounts();

  const memberName = (userId: number) =>
    members.find((m) => m.user_id === userId)?.user_name ?? `#${userId}`;
  const accountName = (accountId: number | null | undefined) =>
    accountId != null ? accounts.find((a) => a.id === accountId)?.name : undefined;

  const hasAdjustments = (transaction.adjustments ?? []).length > 0;
  const isInstallment = transaction.installment_no != null && transaction.installments_of != null;

  return (
    <div data-testid="transaction-summary" className="mb-4 p-4 rounded-xl bg-accent/30 border border-border/50 space-y-3 text-sm">
      <div className="flex items-center justify-between">
        <span className="font-bold text-foreground flex items-center gap-2">
          <Receipt className="h-4 w-4 text-primary" /> Resumo
        </span>
        {isInstallment && (
          <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 border border-primary/30 px-2 py-0.5 text-[11px] font-bold text-primary">
            <CreditCard className="h-3 w-3" /> Parcela {transaction.installment_no}/{transaction.installments_of}
          </span>
        )}
      </div>

      <div className="space-y-1">
        <p className="text-[11px] font-black uppercase text-muted-foreground flex items-center gap-1">
          <Landmark className="h-3 w-3" /> Quem pagou
        </p>
        {(transaction.payers ?? []).map((payer) => {
          const method = payer.payment_method ?? transaction.payment_method;
          const account = accountName(payer.account_id);
          return (
            <p key={payer.id} className="text-xs text-foreground">
              <span className="font-bold">{memberName(payer.user_id)}</span>
              {' '}pagou <span className="font-bold">{formatCurrency(parseFloat(payer.amount))}</span>
              {method && <> via {paymentMethodLabel(method)}</>}
              {account && <> (conta {account})</>}
            </p>
          );
        })}
      </div>

      <div className="space-y-1">
        <p className="text-[11px] font-black uppercase text-muted-foreground flex items-center gap-1">
          <Users className="h-3 w-3" /> Divisão
        </p>
        {(transaction.splits ?? []).map((split) => (
          <p key={split.id} className="text-xs text-foreground">
            <span className="font-bold">{memberName(split.user_id)}</span>
            {' '}deve <span className="font-bold">{formatCurrency(parseFloat(split.computed_amount))}</span>
          </p>
        ))}
      </div>

      {hasAdjustments && (
        <div className="space-y-1">
          <p className="text-[11px] font-black uppercase text-muted-foreground">Ajustes do documento</p>
          {(transaction.adjustments ?? []).map((adj) => (
            <p key={adj.id} className="text-xs text-foreground">
              {ADJUSTMENT_TYPE_LABELS[adj.type]}
              {adj.description ? ` (${adj.description})` : ''}:{' '}
              <span className={`font-bold ${parseFloat(adj.amount) < 0 ? 'text-emerald-500' : ''}`}>
                {formatCurrency(parseFloat(adj.amount))}
              </span>
            </p>
          ))}
        </div>
      )}
    </div>
  );
}
