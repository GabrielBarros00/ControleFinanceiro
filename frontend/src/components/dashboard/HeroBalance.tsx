import { cn } from '@/lib/utils';
import { formatMoney } from '@/lib/money';
import { MoneyText } from '@/components/money/MoneyText';
import { BudgetBar } from '@/components/ui/budget-bar';

/*
 * HeroBalance — o número protagonista do Início (docs/frontend-redesign/06 §1).
 * Mostra a RESPOSTA ("sobra do mês") + progresso do orçamento, no lugar dos 8
 * cartões redundantes de antes.
 */
interface HeroBalanceProps {
  net: number; // sobra = sua receita − sua despesa (mês)
  spent: number; // sua despesa (mês)
  budget: number; // orçamento total previsto
  daysLeft?: number;
  className?: string;
}

export function HeroBalance({ net, spent, budget, daysLeft, className }: HeroBalanceProps) {
  const pct = budget > 0 ? Math.round((spent / budget) * 100) : 0;
  const over = budget > 0 && spent > budget;

  return (
    <div className={cn('rounded-2xl border border-border bg-card p-6', className)}>
      <p className="text-sm text-muted-foreground">Sobra do mês</p>
      <MoneyText
        value={net}
        kind={net >= 0 ? 'income' : 'expense'}
        size="hero"
        className="mt-1 block"
      />
      <p className="mt-2 text-sm text-muted-foreground">
        Você gastou <span className="font-medium text-foreground">{formatMoney(spent)}</span>
        {budget > 0 ? <> de {formatMoney(budget)} previstos</> : <> este mês</>}
      </p>
      {budget > 0 && (
        <div className="mt-3 space-y-1.5">
          <BudgetBar value={spent} max={budget} />
          <p className="text-xs text-muted-foreground">
            <span className={cn('font-medium', over ? 'text-expense' : 'text-foreground')}>
              {pct}% do orçamento
            </span>
            {typeof daysLeft === 'number' && daysLeft >= 0 && (
              <> · {daysLeft} {daysLeft === 1 ? 'dia restante' : 'dias restantes'}</>
            )}
          </p>
        </div>
      )}
    </div>
  );
}
