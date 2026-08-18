import { ChevronLeft, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import { monthLabel } from '@/lib/date';

/*
 * PeriodPicker — seletor de mês compacto e consistente entre telas
 * (docs/frontend-redesign/04 §4). Controlado: value "YYYY-MM" + onChange.
 */
function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split('-').map(Number);
  const d = new Date(y, m - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

interface PeriodPickerProps {
  value: string; // "YYYY-MM"
  onChange: (month: string) => void;
  /**
   * Teto opcional de navegação. **Não use `max={mês atual}`**: uma compra em 12x
   * cria 11 lançamentos em meses FUTUROS (cada parcela tem o seu
   * `billing_month`), e travar no mês corrente os tornava inalcançáveis — sendo
   * que "Dívidas do mês" e "Endividamento" navegam para frente sem limite e
   * mostram exatamente essas parcelas. O mês futuro vazio é informação
   * legítima; a parcela escondida não.
   */
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
        // h-10/w-10: as setas eram 32×32 com `p-2` — pequenas para o polegar, e
        // são o controle mais tocado das telas com mês.
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-l-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <ChevronLeft className="h-4 w-4" />
      </button>
      {/* `min-w-0` até `sm`: os 132px fixos somavam ~196px de largura
          intransponível dentro do `PageHeader`, e num cabeçalho com duas ações
          isso era o bastante para estourar a tela do celular. O rótulo já é
          curto ("Agosto de 2026" ≈ 105px), então nada trunca na prática. */}
      <span className="min-w-0 select-none px-1 text-center text-sm font-medium text-foreground sm:min-w-[132px] sm:px-0">
        {monthLabel(value)}
      </span>
      <button
        type="button"
        disabled={!canNext}
        onClick={() => canNext && onChange(shiftMonth(value, 1))}
        aria-label="Próximo mês"
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-r-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
      >
        <ChevronRight className="h-4 w-4" />
      </button>
    </div>
  );
}
