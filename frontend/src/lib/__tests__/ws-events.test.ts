import { describe, expect, it, vi } from 'vitest';
import {
  FULL_RESYNC,
  GLOBAIS,
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

  // `GLOBAIS` vem do módulo, não copiada aqui: uma segunda lista manual é
  // exatamente o arranjo que produziu os bugs de contrato desta rodada.
  it('escopa no workspace o que é do workspace, e só isso', () => {
    const keys = keysForEvent('transaction.created', WS_ID) as unknown[][];
    for (const key of keys) {
      const familia = key[0] as string;
      if (GLOBAIS.has(familia)) {
        expect(key, `${familia} é global e não leva workspace`).toEqual([familia]);
      } else {
        expect(key[1], `${familia} é do workspace`).toBe(WS_ID);
      }
    }
    const wsKeys = keysForEvent('workspace.updated', WS_ID) as unknown[][];
    expect(wsKeys).toContainEqual(['workspaces']);
  });

  /*
   * Regressão da auditoria: este bloco antes exigia `key[1] === WS_ID` para TODA
   * chave de `transaction.created` — o contrato antigo virado asserção. Depois do
   * ADR 0021 as chaves de cartão, conta, financiamento e renda deixaram de levar
   * workspace, e `['credit-cards', 7]` não casa com `['credit-cards']` (o
   * TanStack compara por prefixo, e o prefixo é o inverso). Resultado: criar um
   * lançamento não atualizava nada da camada pessoal.
   */
  it.each([
    ['credit-cards'],
    ['statements'],
    ['me-overview'],
    ['me-activity'],
  ])('lançamento invalida %s sem escopo de workspace', (familia) => {
    const keys = keysForEvent('transaction.created', WS_ID) as unknown[][];
    expect(keys).toContainEqual([familia]);
    expect(keys).not.toContainEqual([familia, WS_ID]);
  });

  it('renda e acerto atualizam a visão global', () => {
    for (const tipo of ['income.created', 'settlement.created', 'recurring_income.updated']) {
      const keys = keysForEvent(tipo, WS_ID) as unknown[][];
      expect(keys, tipo).toContainEqual(['me-overview']);
    }
  });

  it('ciclo da fatura atualiza cartões e compromissos, não só a fatura', () => {
    const keys = keysForEvent('credit_card.statement_paid', WS_ID) as unknown[][];
    expect(keys).toContainEqual(['statements']);
    expect(keys).toContainEqual(['credit-cards']);
    expect(keys).toContainEqual(['me-commitments']);
    // Pagar fatura É saída de caixa (ADR 0022) — o mês muda na visão global.
    expect(keys).toContainEqual(['me-overview']);
  });

  // Regressão: 'recurring_income' caía no case 'recurring' de ninguém e devolvia
  // lista vazia — renda recorrente nunca atualizava em tempo real.
  it('renda recorrente tem destino próprio', () => {
    const keys = keysForEvent('recurring_income.created', WS_ID) as unknown[][];
    expect(keys).toContainEqual(['recurring-income']);
    expect(keys).toContainEqual(['income']);
  });

  // Regressão: não existia case 'tag'.
  it('tag tem destino próprio', () => {
    const keys = keysForEvent('tag.updated', WS_ID) as unknown[][];
    expect(keys).toContainEqual(['tags', WS_ID]);
  });

  // Regressão: Endividamento não era invalidado por nenhum caminho. A tela virou
  // `/me/commitments` (global) no ADR 0021 e a família 'liabilities' deixou de
  // existir — o mapa continuava invalidando uma chave que ninguém mais usava.
  it.each([
    'transaction.created',
    'financing.updated',
    'credit_card.statement_paid',
    'recurring.updated',
  ])('%s atualiza os Compromissos', (type) => {
    const keys = keysForEvent(type, WS_ID) as unknown[][];
    expect(keys).toContainEqual(['me-commitments']);
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

  it('sem workspace, ainda atualiza a camada PESSOAL', () => {
    // Antes isto era um `return` seco, e o teste afirmava que nada acontecia.
    // Mas há ações que nascem fora de `/w/:id` — pagar uma fatura em `/me/cards`,
    // pagar uma parcela em `/me/financing` — e elas mexem em cartões,
    // compromissos e no caixa do mês. Descartar a invalidação inteira porque não
    // há workspace deixava essas telas com o número velho até um F5.
    const queryClient = { invalidateQueries: vi.fn() };
    invalidateForEvent(queryClient as never, 'transaction.created', null);

    const chamadas = queryClient.invalidateQueries.mock.calls.map((c) => c[0].queryKey);
    expect(chamadas).toContainEqual(['me-overview']);
    expect(chamadas).toContainEqual(['credit-cards']);
    // E nada do workspace: não há workspace a que se referir.
    for (const chave of chamadas) {
      expect(chave).toHaveLength(1);
    }
  });
});
