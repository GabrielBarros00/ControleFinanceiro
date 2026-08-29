import { CreditCard, Landmark, Receipt, Users } from 'lucide-react';
import { useAuth } from '@/hooks/use-auth';
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
  const { user } = useAuth();
  const { members } = useMembers();
  const { accounts } = usePaymentAccounts();

  const memberName = (userId: number) =>
    members.find((m) => m.user_id === userId)?.user_name ?? `#${userId}`;
  const accountName = (accountId: number | null | undefined) =>
    accountId != null ? accounts.find((a) => a.id === accountId)?.name : undefined;

  const hasAdjustments = (transaction.adjustments ?? []).length > 0;
  const isInstallment = transaction.installment_no != null && transaction.installments_of != null;

  const splits = transaction.splits ?? [];
  const total = parseFloat(transaction.total_amount);
  const minhaParte = splits.reduce(
    (acc, s) => acc + (s.user_id === user?.id ? parseFloat(s.computed_amount) : 0),
    0,
  );
  // Só quando a divisão muda a resposta. Numa despesa inteira de uma pessoa só,
  // repetir o valor do cabeçalho como "sua parte" seria uma linha a mais
  // dizendo o que já está dito 40px acima — e quem abre a despesa de OUTRAS
  // pessoas (acesso completo, ADR 0018) leria "Sua parte R$ 0,00" sobre um
  // rateio em que não entrou.
  const mostrarMinhaParte =
    splits.length > 1 && splits.some((s) => s.user_id === user?.id);

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

      {/* O número que o título do diálogo NÃO responde. Lá em cima está o valor
          cheio do lançamento, que é o certo para um detalhe de despesa; quem
          abre uma conta dividida, porém, veio saber quanto daquilo é seu — e
          isso estava só implícito, na linha do próprio nome no meio da lista de
          divisão. */}
      {mostrarMinhaParte && (
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 rounded-lg bg-card/60 px-3 py-2">
          <span className="text-xs font-semibold text-muted-foreground">Sua parte</span>
          <span className="text-sm">
            <span className="font-bold text-foreground">
              {formatCurrency(minhaParte, transaction.currency)}
            </span>
            <span className="ml-1 text-xs text-muted-foreground">
              de {formatCurrency(total, transaction.currency)}
            </span>
          </span>
        </div>
      )}

      <div className="space-y-1">
        <p className="text-[11px] font-semibold uppercase text-muted-foreground flex items-center gap-1">
          <Landmark className="h-3 w-3" /> Quem pagou
        </p>
        {(transaction.payers ?? []).map((payer) => {
          const method = payer.payment_method ?? transaction.payment_method;
          const account = accountName(payer.account_id);
          return (
            <p key={payer.id} className="text-xs text-foreground">
              <span className="font-bold">{memberName(payer.user_id)}</span>
              {' '}pagou <span className="font-bold">{formatCurrency(parseFloat(payer.amount), transaction.currency)}</span>
              {method && <> via {paymentMethodLabel(method)}</>}
              {account && <> (conta {account})</>}
            </p>
          );
        })}
      </div>

      <div className="space-y-1">
        {/* "Divisão: fulano DEVE R$ 100" era falso na metade dos casos. O rateio
            diz de quem é o consumo, não quem está devendo: quem pagou a conta
            inteira aparecia "devendo" a própria parte, quando na verdade tem a
            receber. Quem responde "quem deve a quem" é o balanço de Acertos, que
            cruza o rateio com os pagadores. */}
        <p className="text-[11px] font-semibold uppercase text-muted-foreground flex items-center gap-1">
          <Users className="h-3 w-3" /> Divisão — a parte de cada um
        </p>
        {(transaction.splits ?? []).map((split) => {
          const meu = user?.id === split.user_id;
          return (
            <p key={split.id} className={`text-xs ${meu ? 'text-foreground' : 'text-muted-foreground'}`}>
              <span className="font-bold">{meu ? 'Você' : memberName(split.user_id)}</span>
              {': '}
              <span className="font-bold">
                {formatCurrency(parseFloat(split.computed_amount), transaction.currency)}
              </span>
            </p>
          );
        })}
      </div>

      {hasAdjustments && (
        <div className="space-y-1">
          <p className="text-[11px] font-semibold uppercase text-muted-foreground">Ajustes do documento</p>
          {(transaction.adjustments ?? []).map((adj) => (
            <p key={adj.id} className="text-xs text-foreground">
              {ADJUSTMENT_TYPE_LABELS[adj.type]}
              {adj.description ? ` (${adj.description})` : ''}:{' '}
              <span className={`font-bold ${parseFloat(adj.amount) < 0 ? 'text-emerald-500' : ''}`}>
                {formatCurrency(parseFloat(adj.amount), transaction.currency)}
              </span>
            </p>
          ))}
        </div>
      )}
    </div>
  );
}
