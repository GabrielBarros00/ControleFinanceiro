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

/** Mês por extenso começando com maiúscula (título): `Setembro de 2026`. */
export function monthTitle(valor?: string | null): string {
  const t = monthLong(valor);
  return t.charAt(0).toUpperCase() + t.slice(1);
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

/** Forma de pagamento → rótulo da tela. */
export const FORMA: Record<string, string> = {
  credit_card: 'Cartão de crédito',
  debit_card: 'Débito',
  pix: 'Pix',
  cash: 'Dinheiro',
  bank_transfer: 'Transferência',
  boleto: 'Boleto',
  other: 'Outro',
};

/** Situação de lançamento → rótulo. */
export const SITUACAO: Record<string, string> = {
  draft: 'Rascunho',
  pending: 'Pendente',
  confirmed: 'Confirmado',
  paid: 'Pago',
  cancelled: 'Cancelado',
};

/** Iniciais de um nome ("Ana Souza" → "AS"). */
export function iniciais(nome?: string | null): string {
  const partes = (nome ?? '').trim().split(/\s+/).filter(Boolean);
  if (!partes.length) return '?';
  const [a, b] = [partes[0], partes.length > 1 ? partes[partes.length - 1] : ''];
  return (a[0] + (b ? b[0] : '')).toUpperCase();
}

/** Matiz fixa por nome (a mesma pessoa tem sempre a mesma cor). */
export function matiz(nome?: string | null): number {
  let h = 0;
  for (const c of nome ?? '') h = (h * 31 + c.charCodeAt(0)) % 360;
  return h;
}

/** Texto digitado → string decimal com 2 casas ("89,9" → "89.90"); vazio se inválido. */
export function paraDecimal(texto: string): string {
  const limpo = texto.replace(/[^\d,.-]/g, '').replace(/\.(?=.*[.,])/g, '').replace(',', '.');
  const n = Number(limpo);
  if (!limpo || !Number.isFinite(n)) return '';
  return n.toFixed(2);
}

/** Decimal do servidor ("89.90") → texto do campo ("89,90"). */
export function paraCampo(valor?: string | null): string {
  if (valor === null || valor === undefined || valor === '') return '';
  const n = Number(valor);
  return Number.isFinite(n) ? n.toFixed(2).replace('.', ',') : String(valor);
}
