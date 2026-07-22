import { cn } from '@/lib/utils';

/*
 * BudgetBar — barra de progresso semântica (docs/frontend-redesign/05 §5):
 * verde < 80%, âmbar 80–100%, vermelho > 100% do orçamento.
 */
export function BudgetBar({ value, max, className }: { value: number; max: number; className?: string }) {
  const ratio = max > 0 ? value / max : 0;
  const pct = Math.min(Math.max(ratio, 0), 1) * 100;
  const tone = ratio > 1 ? 'bg-expense' : ratio >= 0.8 ? 'bg-warning' : 'bg-income';
  return (
    <div
      className={cn('h-2 w-full overflow-hidden rounded-full bg-muted', className)}
      role="progressbar"
      aria-valuenow={Math.round(ratio * 100)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div className={cn('h-full rounded-full transition-all', tone)} style={{ width: `${pct}%` }} />
    </div>
  );
}
