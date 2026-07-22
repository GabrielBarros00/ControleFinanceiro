export const formatCurrency = (value: number | string): string => {
  const amount = typeof value === 'string' ? parseFloat(value.replace(/\D/g, '')) / 100 : value;
  if (isNaN(amount)) return 'R$ 0,00';
  
  return new Intl.NumberFormat('pt-BR', {
    style: 'currency',
    currency: 'BRL',
  }).format(amount);
};

export const parseCurrency = (value: string): number => {
  const digits = value.replace(/\D/g, '');
  return parseFloat(digits) / 100;
};

export const maskCurrency = (value: string): string => {
  const digits = value.replace(/\D/g, '');
  const amount = parseInt(digits) || 0;

  return new Intl.NumberFormat('pt-BR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount / 100);
};

/*
 * formatMoney — formatador canônico do redesign (docs/frontend-redesign/05).
 *
 * Diferente de formatCurrency: interpreta STRING como decimal (ex.: "435.90" da
 * API Decimal = R$ 435,90), não como centavos. Usa o menos tipográfico (U+2212)
 * para negativos e prefixo opcional "+" para positivos. Use este (ou MoneyText)
 * em código novo; formatCurrency permanece para o código existente.
 */
const toNum = (value: number | string): number =>
  typeof value === 'string' ? parseFloat(value) : value;

export interface FormatMoneyOptions {
  /** força o sinal '+' em positivos (negativos sempre levam '−') */
  sign?: boolean;
  /** arredonda para inteiro (heróis, eixos de gráfico) */
  hideCents?: boolean;
}

export function formatMoney(value: number | string, opts: FormatMoneyOptions = {}): string {
  const n = toNum(value);
  if (!Number.isFinite(n)) return 'R$ 0,00';
  const digits = opts.hideCents ? 0 : 2;
  const body = new Intl.NumberFormat('pt-BR', {
    style: 'currency',
    currency: 'BRL',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(Math.abs(n));
  const prefix = n < 0 ? '−' : opts.sign && n > 0 ? '+' : '';
  return `${prefix}${body}`;
}

/** Valor compacto para eixos/labels curtos: "R$ 1,2 mil", "R$ 3 mi". */
export function formatCompact(value: number | string): string {
  const n = toNum(value);
  if (!Number.isFinite(n)) return 'R$ 0';
  const abs = Math.abs(n);
  const sign = n < 0 ? '−' : '';
  const fmt = (v: number, suffix: string) =>
    `${sign}R$ ${new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 }).format(v)}${suffix}`;
  if (abs >= 1_000_000) return fmt(abs / 1_000_000, ' mi');
  if (abs >= 1_000) return fmt(abs / 1_000, ' mil');
  return `${sign}${formatMoney(abs, { hideCents: true })}`;
}
