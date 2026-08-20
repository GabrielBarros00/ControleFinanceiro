// Modelo de recorrência compartilhado entre Despesas Recorrentes e Rendas.
// Preset (interval=1): Diário/Semanal/Mensal/Anual com campos de fase (day_of_*).
// Personalizado (interval>1): "a cada N períodos" ancorado em start_date.

export type RecurrenceFrequency = 'daily' | 'weekly' | 'monthly' | 'yearly';

export const WEEKDAYS = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo'];
export const MONTHS = [
  'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
  'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro',
];

export const UNIT_PLURAL: Record<RecurrenceFrequency, string> = {
  daily: 'Dias',
  weekly: 'Semanas',
  monthly: 'Meses',
  yearly: 'Anos',
};

export const PRESET_LABEL: Record<RecurrenceFrequency, string> = {
  daily: 'Diário',
  weekly: 'Semanal',
  monthly: 'Mensal',
  yearly: 'Anual',
};

/** Como a série termina (ADR 0030). */
export type RecurrenceEndMode = 'never' | 'on' | 'after';

export interface RecurrenceValue {
  custom: boolean;
  frequency: RecurrenceFrequency;
  interval: number;
  start_date: string; // YYYY-MM-DD
  day_of_week: number;
  day_of_month: number;
  month_of_year: number;
  /** `never` = sem fim, que era a única opção antes. */
  end_mode: RecurrenceEndMode;
  end_date: string;         // YYYY-MM-DD, quando end_mode === 'on'
  end_after: number;        // nº de ocorrências, quando end_mode === 'after'
}

export interface RecurrenceItemLike {
  frequency: RecurrenceFrequency;
  interval?: number | null;
  start_date?: string | null;
  end_date?: string | null;
  day_of_week?: number | null;
  day_of_month: number;
  month_of_year?: number | null;
  occurrences_total?: number | null;
  occurrences_remaining?: number | null;
}

// 1º dia do mês corrente (componentes locais, sem armadilha de fuso do toISOString).
// Default de start_date: garante que o mês corrente CONTE (dia < hoje não some).
const firstOfCurrentMonth = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`;
};

export function defaultRecurrenceValue(): RecurrenceValue {
  return {
    custom: false,
    frequency: 'monthly',
    interval: 1,
    start_date: firstOfCurrentMonth(),
    day_of_week: 0,
    day_of_month: 1,
    month_of_year: 1,
    end_mode: 'never',
    end_date: '',
    end_after: 12,
  };
}

/** Alcance da materialização quando a data de início é retroativa. */
export type MaterializeScope = 'past' | 'current' | 'future';

/**
 * `true` quando start_date cai ANTES do mês corrente.
 *
 * Só nesse caso a pergunta faz sentido: com data no mês atual (ou à frente) não
 * existe histórico a decidir — o backend materializa o mês corrente e pronto.
 */
export function isRetroactiveStart(startDate?: string | null): boolean {
  if (!startDate) return false;
  return startDate.slice(0, 7) < firstOfCurrentMonth().slice(0, 7);
}

export function recurrenceFromItem(item: RecurrenceItemLike): RecurrenceValue {
  const interval = item.interval ?? 1;
  return {
    custom: interval > 1,
    frequency: item.frequency,
    interval,
    start_date: item.start_date ?? firstOfCurrentMonth(),
    day_of_week: item.day_of_week ?? 0,
    day_of_month: item.day_of_month ?? 1,
    month_of_year: item.month_of_year ?? 1,
    // Volta sempre como `on` quando há fim: o servidor só persiste `end_date`,
    // e reconstruir "por N vezes" a partir dela seria adivinhar a intenção —
    // duas séries diferentes podem terminar no mesmo dia.
    end_mode: item.end_date ? 'on' : 'never',
    end_date: item.end_date ?? '',
    end_after: item.occurrences_total ?? 12,
  };
}

/** Rótulo curto para tabelas ("A cada 2 semanas", "Toda terça", "Dia 5"...). */
export function recurrenceLabel(item: RecurrenceItemLike): string {
  const base = recurrenceBaseLabel(item);
  if (!item.end_date) return base;
  // "· até 12/2038 · 87 restantes" — sem isso a mensalidade de doze anos era
  // indistinguível de uma assinatura sem fim (ADR 0030).
  const fim = `até ${item.end_date.slice(5, 7)}/${item.end_date.slice(0, 4)}`;
  const restam =
    item.occurrences_remaining != null && item.occurrences_total != null
      ? ` · ${item.occurrences_remaining} de ${item.occurrences_total} restantes`
      : '';
  return `${base} · ${fim}${restam}`;
}

function recurrenceBaseLabel(item: RecurrenceItemLike): string {
  const interval = item.interval ?? 1;
  if (interval > 1) {
    return `A cada ${interval} ${UNIT_PLURAL[item.frequency].toLowerCase()}`;
  }
  if (item.frequency === 'daily') return 'Todo dia';
  if (item.frequency === 'weekly') return `Toda ${WEEKDAYS[item.day_of_week ?? 0]?.toLowerCase() ?? ''}`;
  if (item.frequency === 'yearly') {
    return `Todo ano em ${item.day_of_month}/${String(item.month_of_year ?? 1).padStart(2, '0')}`;
  }
  return `Dia ${item.day_of_month}`;
}

/**
 * Como a série termina, no formato da API (ADR 0030).
 *
 * `end_after_occurrences` é convertido em `end_date` NO SERVIDOR: reproduzir aqui
 * a aritmética de ocorrências (o "a cada N" ancorado, o dia limitado ao fim do
 * mês, o piso de `start_date`) daria duas implementações da mesma conta, e duas
 * implementações divergem.
 *
 * `end_date: null` em `never` é explícito, não omitido: no PATCH parcial das
 * rotas, campo ausente significa "não mexe" — e tirar o fim de uma série é
 * justamente uma das coisas que se quer poder fazer.
 */
function fimDaSerie(v: RecurrenceValue) {
  if (v.end_mode === 'on') return { end_date: v.end_date || null };
  if (v.end_mode === 'after') {
    return { end_after_occurrences: Math.max(1, Math.floor(v.end_after || 1)) };
  }
  return { end_date: null as string | null };
}

/** Campos de recorrência aceitos por ambas as rotas (recurring e recurring-income). */
export function toRecurrencePayload(v: RecurrenceValue) {
  if (v.custom) {
    // Personalizado: tudo deriva de start_date no backend
    return {
      frequency: v.frequency,
      interval: Math.max(1, Math.floor(v.interval || 1)),
      start_date: v.start_date,
      day_of_month: 1,
      day_of_week: null as number | null,
      month_of_year: null as number | null,
      ...fimDaSerie(v),
    };
  }
  return {
    frequency: v.frequency,
    interval: 1,
    // Preset também carrega start_date: "vale a partir de" (backend filtra as
    // ocorrências anteriores). null só quando o usuário limpa o campo.
    start_date: v.start_date || null,
    day_of_month: v.day_of_month,
    day_of_week: v.frequency === 'weekly' ? v.day_of_week : null,
    month_of_year: v.frequency === 'yearly' ? v.month_of_year : null,
    ...fimDaSerie(v),
  };
}
