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

export interface RecurrenceValue {
  custom: boolean;
  frequency: RecurrenceFrequency;
  interval: number;
  start_date: string; // YYYY-MM-DD
  day_of_week: number;
  day_of_month: number;
  month_of_year: number;
}

export interface RecurrenceItemLike {
  frequency: RecurrenceFrequency;
  interval?: number | null;
  start_date?: string | null;
  day_of_week?: number | null;
  day_of_month: number;
  month_of_year?: number | null;
}

const today = () => new Date().toISOString().slice(0, 10);

export function defaultRecurrenceValue(): RecurrenceValue {
  return {
    custom: false,
    frequency: 'monthly',
    interval: 1,
    start_date: today(),
    day_of_week: 0,
    day_of_month: 1,
    month_of_year: 1,
  };
}

export function recurrenceFromItem(item: RecurrenceItemLike): RecurrenceValue {
  const interval = item.interval ?? 1;
  return {
    custom: interval > 1,
    frequency: item.frequency,
    interval,
    start_date: item.start_date ?? today(),
    day_of_week: item.day_of_week ?? 0,
    day_of_month: item.day_of_month ?? 1,
    month_of_year: item.month_of_year ?? 1,
  };
}

/** Rótulo curto para tabelas ("A cada 2 semanas", "Toda terça", "Dia 5"...). */
export function recurrenceLabel(item: RecurrenceItemLike): string {
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
    };
  }
  return {
    frequency: v.frequency,
    interval: 1,
    start_date: null as string | null,
    day_of_month: v.day_of_month,
    day_of_week: v.frequency === 'weekly' ? v.day_of_week : null,
    month_of_year: v.frequency === 'yearly' ? v.month_of_year : null,
  };
}
