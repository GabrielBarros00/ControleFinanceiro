import { CreditCard as CardIcon, Trash2 } from 'lucide-react';
import { formatMoney } from '@/lib/money';
import { cn } from '@/lib/utils';

/*
 * CreditCardVisual — cartão com identidade de cartão (docs/frontend-redesign/05 §5,
 * 06 §4): gradiente da marca, "disponível" em destaque, barra de uso do limite.
 * Substitui a caixa-com-borda genérica (H6).
 */
interface CreditCardVisualProps {
  name: string;
  limit: number;
  available: number;
  committed: number;
  closingDay: number;
  dueDay: number;
  selected?: boolean;
  onClick?: () => void;
  onDelete?: () => void;
}

export function CreditCardVisual({
  name,
  limit,
  available,
  committed,
  closingDay,
  dueDay,
  selected,
  onClick,
  onDelete,
}: CreditCardVisualProps) {
  const usedPct = limit > 0 ? Math.min((committed / limit) * 100, 100) : 0;

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'group relative aspect-[1.9/1] w-full overflow-hidden rounded-2xl bg-gradient-to-br from-brand to-brand-hover p-5 text-left text-primary-foreground transition-all',
        selected
          ? 'ring-2 ring-brand ring-offset-2 ring-offset-background'
          : 'opacity-95 hover:opacity-100',
      )}
    >
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <CardIcon className="h-6 w-6 opacity-90" />
          <span className="font-semibold">{name}</span>
        </div>
        {onDelete && (
          <span
            role="button"
            tabIndex={0}
            aria-label="Excluir cartão"
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
            className="rounded-md p-1 text-primary-foreground/70 opacity-0 transition-opacity hover:bg-white/15 hover:text-primary-foreground group-hover:opacity-100"
          >
            <Trash2 className="h-4 w-4" />
          </span>
        )}
      </div>

      <p className="mt-5 text-xs text-primary-foreground/70">Disponível</p>
      <p className="tabular text-2xl font-semibold">{formatMoney(available)}</p>

      <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-white/20">
        <div className="h-full rounded-full bg-white/80" style={{ width: `${usedPct}%` }} />
      </div>

      <div className="mt-2.5 flex items-center justify-between text-xs text-primary-foreground/85">
        <span className="tabular">Limite {formatMoney(limit)}</span>
        <span>Fecha dia {closingDay} · vence {dueDay}</span>
      </div>
    </button>
  );
}
