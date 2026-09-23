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

/** Mês `YYYY-MM` → `09/2026`. */
export function month(valor?: string | null): string {
  if (!valor) return '—';
  const m = /^(\d{4})-(\d{2})/.exec(valor);
  return m ? `${m[2]}/${m[1]}` : valor;
}
