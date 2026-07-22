import { ChevronLeft, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';

/*
 * PeriodPicker — seletor de mês compacto e consistente entre telas
 * (docs/frontend-redesign/04 §4). Controlado: value "YYYY-MM" + onChange.
 */
function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split('-').map(Number);
  const d = new Date(y, m - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function monthLabel(month: string): string {
  const [y, m] = month.split('-').map(Number);
  const s = new Date(y, m - 1, 1).toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' });
  // "julho de 2026" -> "Julho de 2026" (só a inicial; evita "De" no capitalize do CSS)
  return s.charAt(0).toUpperCase() + s.slice(1);
}

interface PeriodPickerProps {
  value: string; // "YYYY-MM"
  onChange: (month: string) => void;
  /** não permite avançar além deste mês (ex.: mês atual) */
  max?: string;
  className?: string;
}

export function PeriodPicker({ value, onChange, max, className }: PeriodPickerProps) {
  const canNext = !max || value < max;
  return (
    <div className={cn('inline-flex items-center rounded-lg border border-border bg-card', className)}>
      <button
        type="button"
        onClick={() => onChange(shiftMonth(value, -1))}
        aria-label="Mês anterior"
        className="rounded-l-lg p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <ChevronLeft className="h-4 w-4" />
      </button>
      <span className="min-w-[132px] select-none text-center text-sm font-medium text-foreground">
        {monthLabel(value)}
      </span>
      <button
        type="button"
        disabled={!canNext}
        onClick={() => canNext && onChange(shiftMonth(value, 1))}
        aria-label="Próximo mês"
        className="rounded-r-lg p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
      >
        <ChevronRight className="h-4 w-4" />
      </button>
    </div>
  );
}
