import { Link } from 'react-router-dom';
import { cn } from '@/lib/utils';
import { formatMoney } from '@/lib/money';
import { MoneyText } from '@/components/money/MoneyText';
import { BudgetBar } from '@/components/ui/budget-bar';

/*
 * HeroBalance — o número protagonista do painel (docs/frontend-redesign/06 §1),
 * no lugar dos 8 cartões redundantes de antes.
 *
 * O rótulo é PARÂMETRO desde a Onda 5. Ele era fixo em "Sobra do mês", e o
 * painel do workspace exibia ali um resultado pessoal (renda global menos
 * despesa local) que não era nem sobra nem do workspace — além de repetir, com
 * outro nome, o tile "Resultado do mês" logo ao lado. Cada tela agora declara
 * que número está protagonizando.
 */
interface HeroBalanceProps {
  /** O que o número grande significa nesta tela. */
  label: string;
  hero: number;
  /** Cor do número: `expense` pinta de vermelho mesmo sendo positivo. */
  heroKind?: 'income' | 'expense';
  spent: number; // sua despesa (mês)
  /** Meta PESSOAL do mês. Tem que ser a do usuário: `spent` é a parte dele. */
  budget: number;
  daysLeft?: number;
  /** moeda-base do workspace — default BRL */
  currency?: string;
  /** Rota para definir a meta pessoal quando ainda não há nenhuma. */
  budgetHref?: string;
  className?: string;
}

export function HeroBalance({
  label,
  hero,
  heroKind,
  spent,
  budget,
  daysLeft,
  currency,
  budgetHref,
  className,
}: HeroBalanceProps) {
  const fmt = (value: number) => formatMoney(value, { currency });
  const pct = budget > 0 ? Math.round((spent / budget) * 100) : 0;
  const diasRestantes =
    typeof daysLeft === 'number' && daysLeft >= 0 ? (
      <> · {daysLeft} {daysLeft === 1 ? 'dia restante' : 'dias restantes'}</>
    ) : null;
  const over = budget > 0 && spent > budget;

  return (
    <div className={cn('rounded-2xl border border-border bg-card p-6', className)}>
      <p className="text-sm text-muted-foreground">{label}</p>
      <MoneyText
        value={hero}
        kind={heroKind ?? (hero >= 0 ? 'income' : 'expense')}
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
          {budgetHref ? (
            <>
              {typeof daysLeft === 'number' && daysLeft >= 0 ? ' · ' : null}
              <Link to={budgetHref} className="font-medium text-brand hover:underline">
                Definir minha meta
              </Link>
            </>
          ) : null}
        </p>
      )}
    </div>
  );
}
