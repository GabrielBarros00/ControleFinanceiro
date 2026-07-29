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
  /** moeda-base do workspace — default BRL */
  currency?: string;
  className?: string;
}

export function HeroBalance({ net, spent, budget, daysLeft, currency, className }: HeroBalanceProps) {
  const fmt = (value: number) => formatMoney(value, { currency });
  const pct = budget > 0 ? Math.round((spent / budget) * 100) : 0;
  const diasRestantes =
    typeof daysLeft === 'number' && daysLeft >= 0 ? (
      <> · {daysLeft} {daysLeft === 1 ? 'dia restante' : 'dias restantes'}</>
    ) : null;
  const over = budget > 0 && spent > budget;

  return (
    <div className={cn('rounded-2xl border border-border bg-card p-6', className)}>
      <p className="text-sm text-muted-foreground">Sobra do mês</p>
      <MoneyText
        value={net}
        kind={net >= 0 ? 'income' : 'expense'}
        size="hero"
        currency={currency}
        className="mt-1 block"
      />
      <p className="mt-2 text-sm text-muted-foreground">
        Você gastou <span className="font-medium text-foreground">{fmt(spent)}</span>
        {budget > 0 ? <> de {fmt(budget)} previstos</> : <> este mês</>}
      </p>
      {budget > 0 ? (
        <div className="mt-3 space-y-1.5">
          <BudgetBar value={spent} max={budget} />
          <p className="text-xs text-muted-foreground">
            <span className={cn('font-medium', over ? 'text-expense' : 'text-foreground')}>
              {pct}% do orçamento
            </span>
            {diasRestantes}
          </p>
        </div>
      ) : (
        // Sem orçamento o card ficava com a metade de baixo VAZIA (ele estica
        // para acompanhar a coluna de tiles ao lado). Os dias restantes já são
        // úteis sozinhos e dão contexto ao "sobra do mês".
        <p className="mt-3 text-xs text-muted-foreground">
          {typeof daysLeft === 'number' && daysLeft >= 0
            ? `${daysLeft === 1 ? 'Falta 1 dia' : `Faltam ${daysLeft} dias`} para fechar o mês`
            : null}
        </p>
      )}
    </div>
  );
}
