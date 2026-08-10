// Fuso fixo ANTES de qualquer uso de Date: as regressões de data (mês/dia
// virando o seguinte após as 21h) só se manifestam em offset negativo, e o CI
// roda em UTC. `test.env` do vite.config define o mesmo valor; reforçamos aqui
// porque o Node lê TZ na primeira construção de Date.
process.env.TZ = 'America/Sao_Paulo';

import '@testing-library/jest-dom';
import { beforeAll, afterEach, afterAll, vi } from 'vitest';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';

// Mock matchMedia for jsdom
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation(query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(), // deprecated
    removeListener: vi.fn(), // deprecated
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// `scrollIntoView` não existe no jsdom, e todo componente que mantém o item
// destacado visível ao navegar por teclado o chama (`CurrencyCombobox`, os menus
// do Base UI). Sem este stub, abrir um desses num teste morre com
// `TypeError: el?.scrollIntoView is not a function` — falha de ambiente que se
// disfarça de falha do componente.
Element.prototype.scrollIntoView = vi.fn();

const BASE_URL = 'http://localhost:8000/api/v1';

// Default Handlers
export const handlers = [
  http.get(`${BASE_URL}/auth/me`, () => {
    return HttpResponse.json({
      id: 1,
      name: 'Test User',
      email: 'test@example.com',
      is_active: true,
      needs_onboarding: false
    });
  }),
  http.get(`${BASE_URL}/workspaces`, () => {
    return HttpResponse.json([
      { id: 1, name: 'Main Workspace', description: 'Test' }
    ]);
  }),
  http.get(`${BASE_URL}/workspaces/`, () => {
    return HttpResponse.json([
      { id: 1, name: 'Main Workspace', description: 'Test' }
    ]);
  }),
  // Coleções auxiliares que várias telas carregam por baixo dos panos. Sem
  // handler, `onUnhandledRequest: 'error'` cospe um erro do MSW no meio da saída
  // dos testes a cada rodada — ruído constante em que uma requisição REALMENTE
  // inesperada passaria despercebida.
  http.get(`${BASE_URL}/workspaces/:id/payment-accounts`, () => HttpResponse.json([])),
  http.get(`${BASE_URL}/workspaces/:id/transactions/`, () =>
    HttpResponse.json({
      items: [], total: 0, total_amount: '0.00', page: 1, limit: 10, total_pages: 1,
    })
  ),
];

export const server = setupServer(...handlers);

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
