import { afterEach, describe, expect, it, vi } from 'vitest';
import { statementAlert, type StatementAlertInput } from '../statement-alert';

/*
 * O ambiente roda em America/Sao_Paulo (vite.config.ts define TZ). Datas de
 * fechamento/vencimento chegam como meia-noite sem offset — o mesmo formato que
 * já causou o bug do "fecha dia 28 exibindo 27".
 */

afterEach(() => {
  vi.useRealTimers();
});

function hoje(iso: string) {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(iso));
}

const fatura = (over: Partial<StatementAlertInput> = {}): StatementAlertInput => ({
  status: 'closed',
  closing_date: '2026-08-28T00:00:00',
  due_date: '2026-09-07T00:00:00',
  amount: 308.4,
  ...over,
});

describe('statementAlert', () => {
  it('fatura paga vira confirmação, não alerta de cobrança', () => {
    hoje('2026-09-10T15:00:00Z');
    const a = statementAlert(fatura({ status: 'paid' }))!;
    expect(a.tone).toBe('success');
    expect(a.short).toBe('Fatura paga');
  });

  it('não paga e vencida é o alerta mais grave', () => {
    hoje('2026-09-10T15:00:00Z'); // 3 dias depois do vencimento
    const a = statementAlert(fatura({ is_overdue: true }))!;
    expect(a.tone).toBe('danger');
    expect(a.short).toBe('Fatura vencida');
    expect(a.detail).toContain('07/09/2026');
    expect(a.detail).toContain('há 3 dias');
  });

  it('fechada com vencimento próximo avisa em âmbar', () => {
    hoje('2026-09-04T15:00:00Z'); // faltam 3 dias
    const a = statementAlert(fatura())!;
    expect(a.tone).toBe('warning');
    expect(a.short).toBe('Vence em 3 dias');
    expect(a.title).toContain('fechada');
  });

  it('fechada com vencimento longe é informativo', () => {
    hoje('2026-08-29T15:00:00Z'); // faltam 9 dias
    const a = statementAlert(fatura())!;
    expect(a.tone).toBe('info');
    expect(a.short).toContain('07/09');
  });

  it('vence hoje/amanhã usa a palavra, não "em 0 dias"', () => {
    hoje('2026-09-07T15:00:00Z');
    expect(statementAlert(fatura())!.short).toBe('Vence hoje');
    hoje('2026-09-06T15:00:00Z');
    expect(statementAlert(fatura())!.short).toBe('Vence amanhã');
  });

  it('aberta longe do fechamento não avisa nada', () => {
    hoje('2026-08-10T15:00:00Z'); // fecha só em 28/08
    expect(statementAlert(fatura({ status: 'open' }))).toBeNull();
  });

  it('aberta perto do fechamento avisa que a próxima compra rola de fatura', () => {
    hoje('2026-08-26T15:00:00Z'); // faltam 2 dias
    const a = statementAlert(fatura({ status: 'open' }))!;
    expect(a.tone).toBe('info');
    expect(a.short).toBe('Fecha em 2 dias');
    expect(a.detail).toContain('próxima fatura');
  });

  // O ciclo corrente é materializado mesmo sem compras: avisar sobre R$ 0,00
  // treinaria o usuário a ignorar os avisos.
  it('fatura zerada não vira alerta, nem fechada nem vencida', () => {
    hoje('2026-09-10T15:00:00Z');
    expect(statementAlert(fatura({ amount: 0 }))).toBeNull();
    expect(statementAlert(fatura({ amount: 0, is_overdue: true }))).toBeNull();
    expect(statementAlert(fatura({ amount: 0, status: 'open' }))).toBeNull();
  });

  it('respeita a moeda-base do workspace', () => {
    hoje('2026-09-04T15:00:00Z');
    expect(statementAlert(fatura(), 'USD')!.detail).toContain('US$');
  });

  // Regressão do off-by-one: meia-noite lida como UTC voltava um dia e o alerta
  // dizia "vencida" no próprio dia do vencimento.
  it('no dia do vencimento ainda não está vencida', () => {
    hoje('2026-09-07T23:00:00Z'); // 20h em Brasília, ainda dia 07
    const a = statementAlert(fatura())!;
    expect(a.tone).toBe('warning');
    expect(a.short).toBe('Vence hoje');
  });
});
