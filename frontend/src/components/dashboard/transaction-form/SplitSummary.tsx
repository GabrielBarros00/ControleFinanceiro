import { formatCurrency } from '@/lib/money';

const formatPercent = (value: number) =>
  value.toLocaleString('pt-BR', { maximumFractionDigits: 2 });

interface SplitSummaryProps {
  method: 'equal' | 'percentage' | 'fixed';
  splits: { user_id: string; value: number }[];
  totalAmount: number;
  /** moeda do lançamento — o resumo fala a MESMA moeda dos campos acima */
  currency?: string;
  testId?: string;
}

// Resumo vivo da divisão: verde quando fecha, âmbar mostrando o que falta
export function SplitSummary({ method, splits, totalAmount, currency = 'BRL', testId = 'split-summary' }: SplitSummaryProps) {
  const fmt = (value: number) => formatCurrency(value, currency);
  const count = splits.length;
  if (!count) return null;

  if (method === 'equal') {
    if (totalAmount <= 0) return null;
    return (
      <p data-testid={testId} className="text-xs font-semibold text-muted-foreground">
        Dividido igualmente entre {count} participante{count > 1 ? 's' : ''} — aprox. {fmt(totalAmount / count)} cada
      </p>
    );
  }

  if (method === 'percentage') {
    const sum = splits.reduce((acc, s) => acc + (Number.isFinite(s.value) ? s.value : 0), 0);
    const closed = Math.abs(sum - 100) <= 0.001;
    return (
      <p data-testid={testId} className={`text-xs font-semibold ${closed ? 'text-emerald-500' : 'text-amber-500'}`}>
        {closed
          ? 'Percentuais fecham 100%'
          : sum < 100
            ? `Somam ${formatPercent(sum)}% — faltam ${formatPercent(100 - sum)}%`
            : `Somam ${formatPercent(sum)}% — ${formatPercent(sum - 100)}% acima de 100%`}
      </p>
    );
  }

  const sumCents = splits.reduce(
    (acc, s) => acc + Math.round((Number.isFinite(s.value) ? s.value : 0) * 100), 0
  );
  const totalCents = Math.round(totalAmount * 100);
  const closed = totalCents > 0 && sumCents === totalCents;
  const diff = Math.abs(totalCents - sumCents) / 100;
  return (
    <p data-testid={testId} className={`text-xs font-semibold ${closed ? 'text-emerald-500' : 'text-amber-500'}`}>
      {closed
        ? `Valores fecham ${fmt(totalAmount)}`
        : sumCents < totalCents
          ? `Somam ${fmt(sumCents / 100)} de ${fmt(totalAmount)} — faltam ${fmt(diff)}`
          : `Somam ${fmt(sumCents / 100)} de ${fmt(totalAmount)} — ${fmt(diff)} acima do total`}
    </p>
  );
}
