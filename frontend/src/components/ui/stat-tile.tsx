import type { ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/utils';
import { MoneyText, type MoneyKind } from '@/components/money/MoneyText';
import { formatMoney } from '@/lib/money';

/*
 * StatTile — métrica calma (docs/frontend-redesign/05 §3): rótulo pequeno, valor
 * via MoneyText, hint discreto. Substitui os cartões "loud" com borda colorida.
 */
interface StatTileProps {
  label: string;
  value: number | string;
  kind?: MoneyKind;
  hint?: ReactNode;
  icon?: LucideIcon;
  /** moeda-base do workspace — default BRL */
  currency?: string;
  className?: string;
}

/*
 * Tamanho do número no CELULAR, pelo comprimento do texto formatado.
 *
 * As grades de métrica passaram a ter DUAS colunas abaixo de `sm` — com uma só,
 * quatro números ocupavam a tela inteira e ninguém chegava ao conteúdo sem
 * rolar. Em duas colunas sobram ~147px por célula, e "+R$ 1.661.142,35" a 20px
 * não cabe: com `break-words` ele quebrava NO MEIO DO NÚMERO ("1.661.142,3" /
 * "5"), que é pior do que não caber. Encolher é a única saída que preserva o
 * valor inteiro e legível — truncar dinheiro nunca é opção.
 *
 * No desktop nada disso vale: lá é `sm:text-2xl` fixo e há espaço de sobra.
 */
function classeDeTamanho(texto: string): string {
  if (texto.length > 15) return 'text-sm';
  if (texto.length > 12) return 'text-base';
  return 'text-xl';
}

export function StatTile({ label, value, kind = 'neutral', hint, icon: Icon, currency, className }: StatTileProps) {
  // Mesmo caminho de formatação do `MoneyText` (o sinal de `expense`/`income`
  // conta no comprimento) — ver `components/money/MoneyText.tsx`.
  const n = typeof value === 'string' ? parseFloat(value) : value;
  const magnitude = Math.abs(Number.isFinite(n) ? n : 0);
  const texto =
    kind === 'expense'
      ? formatMoney(-magnitude, { currency })
      : kind === 'income'
        ? formatMoney(magnitude, { sign: true, currency })
        : formatMoney(magnitude, { currency });

  return (
    <div className={cn('min-w-0 rounded-xl border border-border bg-card p-3 sm:p-4', className)}>
      <div className="flex items-start justify-between gap-1">
        <p className="min-w-0 text-xs text-muted-foreground sm:text-sm">{label}</p>
        {Icon && <Icon className="h-4 w-4 shrink-0 text-muted-foreground/70" />}
      </div>
      <MoneyText
        value={value}
        kind={kind}
        size="lg"
        currency={currency}
        className={cn('mt-1 block whitespace-nowrap sm:text-2xl', classeDeTamanho(texto))}
      />
      {hint && <p className="mt-1 text-[11px] text-muted-foreground sm:text-xs">{hint}</p>}
    </div>
  );
}
