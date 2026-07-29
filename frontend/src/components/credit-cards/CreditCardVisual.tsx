import { AlertTriangle, CreditCard as CardIcon, Clock, Pencil, Trash2 } from 'lucide-react';
import { formatMoney } from '@/lib/money';
import { cn } from '@/lib/utils';
import type { StatementAlert } from '@/lib/statement-alert';

// Selo sobre o gradiente da marca: fundo translúcido claro para o texto ficar
// legível sem brigar com o roxo do cartão.
const SELO_POR_TOM: Record<StatementAlert['tone'], string> = {
  danger: 'bg-white text-destructive',
  warning: 'bg-amber-300 text-amber-950',
  info: 'bg-white/25 text-primary-foreground',
  success: 'bg-white/25 text-primary-foreground',
};

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
  /** moeda-base do workspace — default BRL */
  currency?: string;
  /** aviso da fatura que pede atenção (fechada / vencendo / vencida) */
  alert?: StatementAlert | null;
  /** vencimento real da fatura em aberto, em dd/mm */
  dueLabel?: string | null;
  selected?: boolean;
  onClick?: () => void;
  onEdit?: () => void;
  onDelete?: () => void;
}

export function CreditCardVisual({
  name,
  limit,
  available,
  committed,
  closingDay,
  dueDay,
  currency,
  alert,
  dueLabel,
  selected,
  onClick,
  onEdit,
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
        <div className="flex items-center gap-1">
          {onEdit && (
            <span
              role="button"
              tabIndex={0}
              aria-label="Editar cartão"
              onClick={(e) => {
                e.stopPropagation();
                onEdit();
              }}
              className="rounded-md p-1 text-primary-foreground/70 opacity-0 transition-opacity hover:bg-white/15 hover:text-primary-foreground group-hover:opacity-100"
            >
              <Pencil className="h-4 w-4" />
            </span>
          )}
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
      </div>

      {/* O selo mora nesta linha, não no canto superior: lá ele dividia espaço
          com editar/excluir e sumia no hover — justo quando o alerta é vermelho. */}
      <div className="mt-5 flex items-center justify-between gap-2">
        <p className="text-xs text-primary-foreground/70">Disponível</p>
        {alert && (
          <span
            data-testid="card-alert"
            className={cn(
              'inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold',
              SELO_POR_TOM[alert.tone],
            )}
          >
            {alert.tone === 'danger' ? (
              <AlertTriangle className="h-3 w-3" />
            ) : alert.tone === 'warning' ? (
              <Clock className="h-3 w-3" />
            ) : null}
            {alert.short}
          </span>
        )}
      </div>
      <p className="tabular text-2xl font-semibold">{formatMoney(available, { currency })}</p>

      <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-white/20">
        <div className="h-full rounded-full bg-white/80" style={{ width: `${usedPct}%` }} />
      </div>

      <div className="mt-2.5 flex items-center justify-between gap-2 text-xs text-primary-foreground/85">
        <span className="tabular">Limite {formatMoney(limit, { currency })}</span>
        {/* Vencimento REAL da fatura em aberto quando existe; sem fatura, os dias
            configurados do ciclo (o cartão recém-criado ainda não tem data). */}
        <span className="tabular shrink-0">
          {dueLabel ? `Vence ${dueLabel}` : `Fecha dia ${closingDay} · vence ${dueDay}`}
        </span>
      </div>

    </button>
  );
}
