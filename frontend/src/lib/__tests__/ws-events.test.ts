import { describe, expect, it, vi } from 'vitest';
import {
  FULL_RESYNC,
  WS_EVENT_TYPES,
  invalidateForEvent,
  keysForEvent,
} from '../ws-events';

const WS_ID = 7;

describe('keysForEvent', () => {
  it('todo tipo publicado pelo backend invalida alguma query', () => {
    for (const type of WS_EVENT_TYPES) {
      const keys = keysForEvent(type, WS_ID);
      if (keys === FULL_RESYNC) continue;
      expect(keys.length, `evento sem destino: ${type}`).toBeGreaterThan(0);
    }
  });

  it('escopa as chaves no workspace (menos a lista global de workspaces)', () => {
    const keys = keysForEvent('transaction.created', WS_ID) as unknown[][];
    for (const key of keys) {
      expect(key[1]).toBe(WS_ID);
    }
    const wsKeys = keysForEvent('workspace.updated', WS_ID) as unknown[][];
    expect(wsKeys).toContainEqual(['workspaces']);
  });

  // Regressão: 'recurring_income' caía no case 'recurring' de ninguém e devolvia
  // lista vazia — renda recorrente nunca atualizava em tempo real.
  it('renda recorrente tem destino próprio', () => {
    const keys = keysForEvent('recurring_income.created', WS_ID) as unknown[][];
    expect(keys).toContainEqual(['recurring-income', WS_ID]);
    expect(keys).toContainEqual(['income', WS_ID]);
  });

  // Regressão: não existia case 'tag'.
  it('tag tem destino próprio', () => {
    const keys = keysForEvent('tag.updated', WS_ID) as unknown[][];
    expect(keys).toContainEqual(['tags', WS_ID]);
  });

  // Regressão: Endividamento não era invalidado por nenhum caminho.
  it.each([
    'transaction.created',
    'financing.updated',
    'credit_card.statement_paid',
    'recurring.updated',
  ])('%s atualiza o Endividamento', (type) => {
    const keys = keysForEvent(type, WS_ID) as unknown[][];
    expect(keys).toContainEqual(['liabilities', WS_ID]);
  });

  it('lançamento atualiza o ledger mensal e o detalhe aberto', () => {
    const keys = keysForEvent('transaction.updated', WS_ID) as unknown[][];
    expect(keys).toContainEqual(['debts-monthly', WS_ID]);
    expect(keys).toContainEqual(['transaction', WS_ID]);
    expect(keys).toContainEqual(['installment-group', WS_ID]);
  });

  it('troca de moeda-base pede resync completo', () => {
    expect(keysForEvent('workspace.currency_changed', WS_ID)).toBe(FULL_RESYNC);
  });

  it('tipo desconhecido pede resync em vez de ignorar em silêncio', () => {
    expect(keysForEvent('coisa.nova', WS_ID)).toBe(FULL_RESYNC);
  });
});

describe('invalidateForEvent', () => {
  it('invalida as mesmas chaves do WebSocket', () => {
    const queryClient = { invalidateQueries: vi.fn() };
    invalidateForEvent(queryClient as never, 'settlement.created', WS_ID);

    const chamadas = queryClient.invalidateQueries.mock.calls.map((c) => c[0].queryKey);
    expect(chamadas).toContainEqual(['settlements', WS_ID]);
    expect(chamadas).toContainEqual(['debts', WS_ID]);
    expect(chamadas).toContainEqual(['debts-monthly', WS_ID]);
  });

  it('resync completo invalida tudo de uma vez', () => {
    const queryClient = { invalidateQueries: vi.fn() };
    invalidateForEvent(queryClient as never, 'workspace.currency_changed', WS_ID);
    expect(queryClient.invalidateQueries).toHaveBeenCalledTimes(1);
    expect(queryClient.invalidateQueries).toHaveBeenCalledWith();
  });

  it('sem workspace não faz nada', () => {
    const queryClient = { invalidateQueries: vi.fn() };
    invalidateForEvent(queryClient as never, 'transaction.created', null);
    expect(queryClient.invalidateQueries).not.toHaveBeenCalled();
  });
});
