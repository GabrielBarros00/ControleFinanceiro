import { Pencil, Trash2 } from 'lucide-react';
import type { TransactionRead } from '@/types/transaction';
import { MoneyText } from './MoneyText';
import { CategoryGlyph, type CategoryLike } from './CategoryGlyph';
import { paymentMethodLabel } from '@/lib/payment-methods';
import { formatCurrency } from '@/lib/money';
import { cn } from '@/lib/utils';

/*
 * TransactionItem — linha do extrato (docs/frontend-redesign/05 §3, 06 §2).
 * Glifo de categoria + título + meta (categoria · pagamento · parcela · divisão)
 * + valor com cor/sinal corretos. Ações acessíveis por foco e visíveis no mobile.
 */
interface TransactionItemProps {
  tx: TransactionRead;
  category?: CategoryLike | null;
  memberName?: (userId: number) => string;
  canWrite?: boolean;
  onEdit?: (tx: TransactionRead) => void;
  onDelete?: (id: number) => void;
  /** Clicar na linha abre o detalhe/preview do lançamento. */
  onSelect?: (tx: TransactionRead) => void;
}

export function TransactionItem({
  tx,
  category,
  memberName,
  canWrite = true,
  onEdit,
  onDelete,
  onSelect,
}: TransactionItemProps) {
  const amount = parseFloat(tx.total_amount);
  const kind = amount < 0 ? 'income' : 'expense';
  const splits = tx.splits ?? [];
  const isSplit = splits.length > 1;

  const meta: string[] = [];
  if (category?.name) meta.push(category.name);
  meta.push(paymentMethodLabel(tx.payment_method, tx.credit_card_id));
  if (tx.installments_of && tx.installments_of > 1) {
    meta.push(`${tx.installment_no}/${tx.installments_of}`);
  }
  // Lançamento estrangeiro: mostra o valor original ao lado do total em BRL
  if (tx.original_currency && tx.original_amount) {
    meta.push(formatCurrency(parseFloat(tx.original_amount), tx.original_currency));
  }

  return (
    <div
      className={cn(
        'group flex items-center gap-3 rounded-lg px-2 py-2.5 transition-colors hover:bg-muted',
        onSelect && 'cursor-pointer',
      )}
      onClick={onSelect ? () => onSelect(tx) : undefined}
      role={onSelect ? 'button' : undefined}
      tabIndex={onSelect ? 0 : undefined}
      onKeyDown={
        onSelect
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onSelect(tx);
              }
            }
          : undefined
      }
    >
      <CategoryGlyph category={category} />

      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-foreground">{tx.title}</p>
        <p className="truncate text-xs text-muted-foreground">{meta.join(' · ')}</p>
      </div>

      {isSplit && memberName && (
        <div className="hidden items-center -space-x-1.5 sm:flex" aria-hidden>
          {splits.slice(0, 3).map((s) => (
            <span
              key={s.id}
              title={memberName(s.user_id)}
              className="flex h-6 w-6 items-center justify-center rounded-full border border-card bg-brand-subtle text-[10px] font-semibold uppercase text-brand"
            >
              {memberName(s.user_id).slice(0, 1)}
            </span>
          ))}
          {splits.length > 3 && (
            <span className="flex h-6 w-6 items-center justify-center rounded-full border border-card bg-muted text-[10px] font-semibold text-muted-foreground">
              +{splits.length - 3}
            </span>
          )}
        </div>
      )}

      <MoneyText value={amount} kind={kind} currency={tx.currency} className="shrink-0 font-semibold" />

      {(onEdit || onDelete) && (
        <div
          className={cn(
            'flex shrink-0 items-center gap-0.5 transition-opacity',
            'sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100',
          )}
        >
          {onEdit && (
            <button
              type="button"
              aria-label="Editar transação"
              disabled={!canWrite}
              onClick={(e) => { e.stopPropagation(); onEdit(tx); }}
              className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-brand-subtle hover:text-brand disabled:pointer-events-none disabled:opacity-40"
            >
              <Pencil className="h-4 w-4" />
            </button>
          )}
          {onDelete && (
            <button
              type="button"
              aria-label="Excluir transação"
              disabled={!canWrite}
              onClick={(e) => { e.stopPropagation(); onDelete(tx.id); }}
              className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive disabled:pointer-events-none disabled:opacity-40"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          )}
        </div>
      )}
    </div>
  );
}
