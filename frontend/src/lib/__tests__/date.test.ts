import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  apiDateToInput,
  apiDateToMonth,
  currentMonthLocal,
  firstOfCurrentMonth,
  parseApiDate,
  parseApiDay,
  shiftMonth,
  todayLocalISO,
  toLocalISODate,
} from '../date';

/*
 * O ambiente de teste roda em America/Sao_Paulo (vite.config.ts define TZ), que
 * é UTC−3 — o fuso onde os dois bugs de data apareciam.
 */

afterEach(() => {
  vi.useRealTimers();
});

function congelar(iso: string) {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(iso));
}

describe('todayLocalISO / currentMonthLocal', () => {
  // Regressão: às 23:30 de 31/07 em Brasília, toISOString() já dizia 2026-08-01
  it('à noite continua no dia e no mês LOCAIS', () => {
    congelar('2026-08-01T02:30:00Z'); // = 31/07 23:30 em Brasília
    expect(todayLocalISO()).toBe('2026-07-31');
    expect(currentMonthLocal()).toBe('2026-07');
    expect(firstOfCurrentMonth()).toBe('2026-07-01');
  });

  it('de dia bate com o UTC', () => {
    congelar('2026-07-15T15:00:00Z');
    expect(todayLocalISO()).toBe('2026-07-15');
    expect(currentMonthLocal()).toBe('2026-07');
  });

  it('vira o ano corretamente', () => {
    congelar('2027-01-01T02:00:00Z'); // = 31/12/2026 23:00 em Brasília
    expect(currentMonthLocal()).toBe('2026-12');
  });
});

describe('parseApiDate', () => {
  // Regressão: a API serializa instante UTC sem offset e o JS lia como local,
  // então um gasto de 24/07 23:30 aparecia rotulado como 25 de julho.
  it('trata string sem offset como UTC', () => {
    const d = parseApiDate('2026-07-25T02:30:00');
    expect(toLocalISODate(d)).toBe('2026-07-24');
    expect(d.getHours()).toBe(23);
  });

  it('respeita offset explícito quando vem', () => {
    expect(toLocalISODate(parseApiDate('2026-07-25T02:30:00Z'))).toBe('2026-07-24');
    expect(toLocalISODate(parseApiDate('2026-07-24T23:30:00-03:00'))).toBe('2026-07-24');
  });

  it('data pura é dia de calendário, não instante', () => {
    // Sem isso, 2026-07-10 viraria 09/07 em qualquer fuso negativo
    expect(toLocalISODate(parseApiDate('2026-07-10'))).toBe('2026-07-10');
  });

  it('aceita Date direto', () => {
    const d = new Date(2026, 6, 10);
    expect(parseApiDate(d)).toBe(d);
  });
});

describe('parseApiDay', () => {
  // Regressão: fechamento/vencimento da fatura são DIAS de calendário que a API
  // serializa como meia-noite sem offset. Lidos como UTC, viravam 21h do dia
  // anterior em Brasília — o cartão que fecha dia 28 exibia "27/08".
  it('não retrocede um dia em fuso negativo', () => {
    expect(toLocalISODate(parseApiDay('2026-08-28T00:00:00'))).toBe('2026-08-28');
    expect(parseApiDay('2026-08-28T00:00:00').toLocaleDateString('pt-BR')).toBe('28/08/2026');
  });

  it('aceita data pura e Date', () => {
    expect(toLocalISODate(parseApiDay('2026-09-07'))).toBe('2026-09-07');
    const d = new Date(2026, 8, 7);
    expect(parseApiDay(d)).toBe(d);
  });

  it('difere de parseApiDate justamente na meia-noite', () => {
    expect(toLocalISODate(parseApiDate('2026-08-28T00:00:00'))).toBe('2026-08-27');
    expect(toLocalISODate(parseApiDay('2026-08-28T00:00:00'))).toBe('2026-08-28');
  });
});

describe('apiDateToInput / apiDateToMonth', () => {
  it('converte instante da API para a data local do formulário', () => {
    expect(apiDateToInput('2026-07-25T02:30:00')).toBe('2026-07-24');
    expect(apiDateToMonth('2026-07-25T02:30:00')).toBe('2026-07');
  });
});

describe('shiftMonth', () => {
  it('anda para frente e para trás cruzando o ano', () => {
    expect(shiftMonth('2026-07', 1)).toBe('2026-08');
    expect(shiftMonth('2026-12', 1)).toBe('2027-01');
    expect(shiftMonth('2026-01', -1)).toBe('2025-12');
    expect(shiftMonth('2026-07', -13)).toBe('2025-06');
  });

  it('mantém o padding de dois dígitos', () => {
    expect(shiftMonth('2026-09', 1)).toBe('2026-10');
    expect(shiftMonth('2026-10', -1)).toBe('2026-09');
  });
});
