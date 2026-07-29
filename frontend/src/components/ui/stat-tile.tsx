import type { ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/utils';
import { MoneyText, type MoneyKind } from '@/components/money/MoneyText';

/*
 * StatTile — métrica calma (docs/frontend-redesign/05 §3): rótulo pequeno, valor
 * via MoneyText, hint discreto. Substitui os cartões "loud" com borda colorida.
 */
interface StatTileProps {
  label: string;
  value: number | string;
  kind?: MoneyKind;
  hint?: ReactNode;
  icon?: LucideIcon;
  /** moeda-base do workspace — default BRL */
  currency?: string;
  className?: string;
}

export function StatTile({ label, value, kind = 'neutral', hint, icon: Icon, currency, className }: StatTileProps) {
  return (
    <div className={cn('rounded-xl border border-border bg-card p-4', className)}>
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">{label}</p>
        {Icon && <Icon className="h-4 w-4 text-muted-foreground/70" />}
      </div>
      <MoneyText value={value} kind={kind} size="lg" currency={currency} className="mt-1 block" />
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}
