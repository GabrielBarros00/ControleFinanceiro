/*
 * Datas — fuso LOCAL em todo lugar.
 *
 * Duas armadilhas que o app já teve, resolvidas aqui de uma vez:
 *
 * 1. `new Date().toISOString().slice(0, 7)` devolve o mês em UTC. Em Brasília
 *    (UTC−3), depois das 21h do último dia do mês isso já é o mês SEGUINTE — a
 *    tela abria vazia em agosto no dia 31 de julho. Com `.slice(0, 10)` era pior:
 *    todo dia depois das 21h o "hoje" default virava amanhã.
 *
 * 2. A API serializa instantes UTC sem offset ("2026-07-25T02:30:00"), e o JS
 *    interpreta string sem offset como hora LOCAL. Um gasto de 24/07 23:30 em
 *    Brasília voltava como 25/07 02:30 e era rotulado "25 de jul".
 *    `parseApiDate` marca a string como UTC antes de converter.
 */

/** Hoje em YYYY-MM-DD no fuso local. */
export function todayLocalISO(): string {
  return toLocalISODate(new Date());
}

/** Mês corrente em YYYY-MM no fuso local. */
export function currentMonthLocal(): string {
  return todayLocalISO().slice(0, 7);
}

/** 1º dia do mês corrente em YYYY-MM-DD (fuso local). */
export function firstOfCurrentMonth(): string {
  return `${currentMonthLocal()}-01`;
}

/** Date → YYYY-MM-DD usando os componentes locais (nunca toISOString). */
export function toLocalISODate(d: Date): string {
  const mes = String(d.getMonth() + 1).padStart(2, '0');
  const dia = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${mes}-${dia}`;
}

/** Desloca um YYYY-MM em `delta` meses, sem passar por UTC. */
export function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split('-').map(Number);
  const total = y * 12 + (m - 1) + delta;
  const ano = Math.floor(total / 12);
  const mes = (total % 12) + 1;
  return `${ano}-${String(mes).padStart(2, '0')}`;
}

/**
 * Converte uma data vinda da API para Date.
 *
 * O backend guarda instantes em UTC numa coluna sem timezone, então a string
 * chega sem offset. Sem o 'Z' o JS a leria como hora local e o dia exibido
 * saltaria para o seguinte em qualquer lançamento feito à noite.
 */
export function parseApiDate(value: string | Date): Date {
  if (value instanceof Date) return value;
  const temOffset = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value);
  // Data pura (YYYY-MM-DD) é dia de calendário, não instante: monta local para
  // não retroceder um dia em fusos negativos.
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [y, m, d] = value.split('-').map(Number);
    return new Date(y, m - 1, d);
  }
  return new Date(temOffset ? value : `${value}Z`);
}

/** Data da API → YYYY-MM-DD local (para preencher <input type="date">). */
export function apiDateToInput(value: string | Date): string {
  return toLocalISODate(parseApiDate(value));
}

/** Data da API → YYYY-MM local (para casar com o filtro de mês). */
export function apiDateToMonth(value: string | Date): string {
  return apiDateToInput(value).slice(0, 7);
}
