/** Formatação do componente — o servidor manda dinheiro em string decimal ("89.90"). */

export function money(valor: string | number | null | undefined, moeda = 'BRL'): string {
  if (valor === null || valor === undefined || valor === '') return '—';
  const numero = typeof valor === 'number' ? valor : Number(valor);
  if (!Number.isFinite(numero)) return String(valor);
  try {
    return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: moeda }).format(numero);
  } catch {
    return `${moeda} ${numero.toFixed(2)}`;
  }
}

/** Dia civil `YYYY-MM-DD` → `22/09/2026`, sem passar por `Date` (nada de fuso). */
export function day(valor?: string | null): string {
  if (!valor) return '—';
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(valor);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : valor;
}

/** Dia civil `YYYY-MM-DD` → `22/09`, para listas em que o ano é o do contexto. */
export function shortDay(valor?: string | null): string {
  if (!valor) return '—';
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(valor);
  return m ? `${m[3]}/${m[2]}` : valor;
}

/** Mês `YYYY-MM` → `09/2026`. */
export function month(valor?: string | null): string {
  if (!valor) return '—';
  const m = /^(\d{4})-(\d{2})/.exec(valor);
  return m ? `${m[2]}/${m[1]}` : valor;
}

const MESES = [
  'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
  'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro',
];

/** Mês `YYYY-MM` → `setembro de 2026`. Tabela fixa, sem `Intl` nem `Date` (nada de fuso). */
export function monthLong(valor?: string | null): string {
  if (!valor) return '—';
  const m = /^(\d{4})-(\d{2})/.exec(valor);
  const nome = m ? MESES[Number(m[2]) - 1] : undefined;
  return m && nome ? `${nome} de ${m[1]}` : valor;
}

/** Porcentagem inteira de `parte` em `todo` (0–100), para as barras. */
export function percent(parte: string | number, todo: string | number): number {
  const p = Number(parte);
  const t = Number(todo);
  if (!Number.isFinite(p) || !Number.isFinite(t) || t <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((p / t) * 100)));
}

/** `1 lançamento` / `3 lançamentos`: nada de "lançamento(s)" na tela. */
export function plural(n: number, um: string, varios: string): string {
  return `${n} ${n === 1 ? um : varios}`;
}
