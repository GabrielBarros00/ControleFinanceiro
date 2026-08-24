import * as React from 'react';
import type { TransactionRead } from '@/types/transaction';
import { useCategories } from '@/hooks/use-categories';
import { useMembers } from '@/hooks/use-members';
import { formatMoney } from '@/lib/money';
import { useBaseCurrency } from '@/hooks/use-base-currency';
import { TransactionItem } from './TransactionItem';
import { parseApiDate } from '@/lib/date';

/*
 * TransactionLedger — extrato agrupado por dia (docs/frontend-redesign/06 §2).
 * Cabeçalho de dia ("Hoje", "Ontem", "20 jul") + subtotal, e uma TransactionItem
 * por linha. Resolve categoria e nomes de membro uma vez (não por linha).
 */
function dayKey(iso: string): string {
  const d = parseApiDate(iso);
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

function dayLabel(iso: string): string {
  const d = parseApiDate(iso);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  if (same(d, today)) return 'Hoje';
  if (same(d, yesterday)) return 'Ontem';
  return d.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' });
}

interface TransactionLedgerProps {
  transactions: TransactionRead[];
  canWrite?: boolean;
  onEdit?: (tx: TransactionRead) => void;
  onDelete?: (id: number) => void;
  onSelect?: (tx: TransactionRead) => void;
  showDayTotals?: boolean;
}

export function TransactionLedger({
  transactions,
  canWrite,
  onEdit,
  onDelete,
  onSelect,
  showDayTotals = true,
}: TransactionLedgerProps) {
  const { categories } = useCategories();
  const { members } = useMembers();
  const baseCurrency = useBaseCurrency();

  const categoryById = React.useMemo(() => {
    const map = new Map<number, (typeof categories)[number]>();
    for (const c of categories) map.set(c.id, c);
    return map;
  }, [categories]);

  const memberName = React.useCallback(
    (userId: number) => members.find((m) => m.user_id === userId)?.user_name ?? `#${userId}`,
    [members],
  );
  const memberAvatar = React.useCallback(
    (userId: number) => members.find((m) => m.user_id === userId)?.avatar_version,
    [members],
  );

  const groups = React.useMemo(() => {
    const out: { key: string; label: string; items: TransactionRead[]; total: number }[] = [];
    for (const tx of transactions) {
      const key = dayKey(tx.transaction_date);
      let g = out[out.length - 1];
      if (!g || g.key !== key) {
        g = { key, label: dayLabel(tx.transaction_date), items: [], total: 0 };
        out.push(g);
      }
      g.items.push(tx);
      g.total += parseFloat(tx.total_amount);
    }
    return out;
  }, [transactions]);

  const catFor = (tx: TransactionRead) => {
    const id = tx.items?.[0]?.category_id;
    return id != null ? categoryById.get(id) ?? null : null;
  };

  return (
    <div className="space-y-5">
      {groups.map((g) => (
        <div key={g.key}>
          <div className="mb-1 flex items-center justify-between px-2">
            <span className="text-xs font-medium text-muted-foreground">{g.label}</span>
            {showDayTotals && (
              <span className="tabular text-xs text-muted-foreground">{formatMoney(g.total, { currency: baseCurrency })}</span>
            )}
          </div>
          <div className="divide-y divide-border/60">
            {g.items.map((tx) => (
              <TransactionItem
                key={tx.id}
                tx={tx}
                category={catFor(tx)}
                memberName={memberName}
                memberAvatar={memberAvatar}
                canWrite={canWrite}
                onEdit={onEdit}
                onDelete={onDelete}
                onSelect={onSelect}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
