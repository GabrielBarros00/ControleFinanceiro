import { Button } from '@/components/ui/button';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { currentMonthLocal, monthLabel, shiftMonth } from '@/lib/date';

/**
 * O `‹ Agosto/2026 ›` das telas de acerto.
 *
 * Vivia duplicado byte a byte em `MonthlyDebtsSection` e `MySettlementsPage` —
 * inclusive o comentário explicando por que NÃO se usa `capitalize` (a classe do
 * CSS capitaliza cada palavra e produzia "Agosto De 2026"; quem capitaliza é o
 * `monthLabel`). Duas cópias de um controle de navegação é como as duas telas de
 * acerto acabaram divergindo da primeira vez.
 */
interface Props {
  month: string;
  onChange: (month: string) => void;
  className?: string;
}

export function MonthNavigator({ month, onChange, className }: Props) {
  const isCurrentMonth = month === currentMonthLocal();

  return (
    <div
      className={`flex items-center justify-between rounded-xl border border-border bg-accent/30 p-2 ${className ?? ''}`}
    >
      <Button
        variant="ghost"
        size="icon"
        aria-label="Mês anterior"
        onClick={() => onChange(shiftMonth(month, -1))}
      >
        <ChevronLeft className="h-4 w-4" />
      </Button>
      <div className="flex flex-col items-center">
        <span className="text-sm font-semibold text-foreground">{monthLabel(month)}</span>
        {!isCurrentMonth && (
          <button
            type="button"
            onClick={() => onChange(currentMonthLocal())}
            className="text-[10px] font-bold text-primary hover:underline"
          >
            voltar para o mês atual
          </button>
        )}
      </div>
      <Button
        variant="ghost"
        size="icon"
        aria-label="Próximo mês"
        onClick={() => onChange(shiftMonth(month, 1))}
      >
        <ChevronRight className="h-4 w-4" />
      </Button>
    </div>
  );
}
