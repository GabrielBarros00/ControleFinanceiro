import { cn } from '@/lib/utils';
import { formatMoney } from '@/lib/money';

/*
 * MoneyText — fonte única de formatação + semântica de cor de dinheiro
 * (docs/frontend-redesign/05 §1). Quem decide a cor/sinal é o TIPO do lançamento
 * (kind), nunca o sinal cru do número. Isso resolve o bug do "toda despesa verde":
 * uma despesa é sempre vermelha com '−', uma receita verde com '+'.
 */
export type MoneyKind = 'expense' | 'income' | 'transfer' | 'neutral';

const SIZE: Record<NonNullable<MoneyTextProps['size']>, string> = {
  sm: 'text-sm',
  md: 'text-base',
  lg: 'text-2xl font-semibold',
  hero: 'text-4xl font-semibold tracking-tight',
};

export interface MoneyTextProps {
  value: number | string;
  /** decide COR e SINAL. default: 'neutral' (sem cor, sem sinal) */
  kind?: MoneyKind;
  size?: 'sm' | 'md' | 'lg' | 'hero';
  /** força '+'/'−' em income; default: mostra sinal em income/expense */
  showSign?: boolean;
  /** false = sempre --foreground (ex.: colunas neutras) */
  colorize?: boolean;
  /** moeda do lançamento (default BRL) — exibe USD/EUR na própria moeda */
  currency?: string;
  className?: string;
}

export function MoneyText({
  value,
  kind = 'neutral',
  size = 'md',
  showSign,
  colorize = true,
  currency,
  className,
}: MoneyTextProps) {
  const n = typeof value === 'string' ? parseFloat(value) : value;
  const magnitude = Math.abs(Number.isFinite(n) ? n : 0);

  const text =
    kind === 'expense'
      ? formatMoney(-magnitude, { currency }) // sempre '−'
      : kind === 'income'
        ? formatMoney(magnitude, { sign: showSign ?? true, currency })
        : formatMoney(magnitude, { currency });

  const color = !colorize
    ? undefined
    : kind === 'expense'
      ? 'text-expense'
      : kind === 'income'
        ? 'text-income'
        : 'text-foreground';

  return <span className={cn('tabular', color, SIZE[size], className)}>{text}</span>;
}
