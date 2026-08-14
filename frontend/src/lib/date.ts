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

/**
 * Converte um DIA DE CALENDÁRIO que a API serializa como datetime à meia-noite
 * ("2026-08-28T00:00:00") para Date, lendo os componentes como estão.
 *
 * `parseApiDate` marca a string como UTC — correto para instantes (quando a
 * despesa foi lançada), errado para dias de calendário: meia-noite UTC é 21h do
 * dia ANTERIOR em Brasília, e o fechamento/vencimento da fatura aparecia um dia
 * adiantado (cartão que fecha dia 28 exibia "27/08"). Data de vencimento errada
 * num app de finanças é fatura paga com atraso.
 */
export function parseApiDay(value: string | Date): Date {
  if (value instanceof Date) return value;
  const [y, m, d] = value.slice(0, 10).split('-').map(Number);
  return new Date(y, (m || 1) - 1, d || 1);
}

/**
 * Dias de calendário (locais) entre hoje e `target`. Positivo = futuro, 0 = hoje,
 * negativo = passado.
 *
 * Compara os DIAS, não os instantes: "vence em 1 dia" tem que valer o dia
 * inteiro, não virar 0 porque faltam 23 horas.
 */
export function daysUntil(target: string | Date): number {
  const alvo = parseApiDay(target);
  const hoje = new Date();
  const meiaNoite = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  return Math.round((meiaNoite(alvo) - meiaNoite(hoje)) / 86_400_000);
}

/**
 * "2026-07" → "jul." — rótulo curto de mês em PT-BR, para eixos de gráfico.
 *
 * O backend devolvia o nome pronto via `strftime("%b")`, que segue o locale do
 * PROCESSO: no container (locale C) o eixo de Relatórios mostrava "Jan/Feb/May"
 * num app inteiro em português. Formatar aqui deixa o backend livre de locale e
 * o rótulo sempre no idioma de quem lê.
 */
export function monthShortLabel(month: string): string {
  const [y, m] = month.split('-').map(Number);
  if (!y || !m) return month;
  return new Date(y, m - 1, 1).toLocaleDateString('pt-BR', { month: 'short' });
}

/** `2026-08` → `agosto de 2026`. Rótulo por extenso do navegador de mês.
 *
 * Mora aqui, e não junto do componente, porque duas telas navegam pelos mesmos
 * meses: os acertos DESTA casa e os acertos de TODAS (ADR 0027). */
export function monthLabel(month: string): string {
  const [y, m] = month.split('-').map(Number);
  if (!y || !m) return month;
  return new Date(y, m - 1, 1).toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' });
}

/** Data da API → YYYY-MM-DD local (para preencher <input type="date">). */
export function apiDateToInput(value: string | Date): string {
  return toLocalISODate(parseApiDate(value));
}

/** Data da API → YYYY-MM local (para casar com o filtro de mês). */
export function apiDateToMonth(value: string | Date): string {
  return apiDateToInput(value).slice(0, 7);
}
