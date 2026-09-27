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
  // Coleções auxiliares que o formulário de lançamento carrega por baixo dos
  // panos (contas e cartões da pessoa, estabelecimentos do espaço). Sem handler,
  // a requisição falha e o formulário renderiza em estado de erro — o teste
  // passava assim mesmo, exercitando uma tela que o usuário nunca vê.
  //
  // O handler antigo daqui apontava para `/workspaces/:id/payment-accounts`, rota
  // que deixou de existir quando as contas viraram pessoais (ADR 0021): a
  // proteção descrita acima estava protegendo o vazio, e ~100 requisições por
  // execução caíam sem handler.
  http.get(`${BASE_URL}/me/payment-accounts`, () => HttpResponse.json([])),
  http.get(`${BASE_URL}/me/credit-cards/`, () => HttpResponse.json([])),
  http.get(`${BASE_URL}/workspaces/:id/merchants`, () => HttpResponse.json([])),
  http.get(`${BASE_URL}/workspaces/:id/transactions/`, () =>
    HttpResponse.json({
      items: [], total: 0, total_amount: '0.00', page: 1, limit: 10, total_pages: 1,
    })
  ),
];

export const server = setupServer(...handlers);

/*
 * Requisição sem handler REPROVA o teste — não basta imprimir.
 *
 * Com `onUnhandledRequest: 'error'` o MSW só loga e derruba a requisição; o
 * componente cai no estado de erro e o teste segue verde. Foi assim que a
 * suíte chegou a ~100 requisições sem handler por execução sem ninguém notar.
 * Aqui cada uma é anotada e o `afterEach` falha o teste que a disparou, com a
 * lista. `print.error()` mantém o comportamento de antes para a requisição:
 * ela falha, e nunca escapa para um backend de verdade na porta 8000.
 */
const naoTratadas: string[] = [];

beforeAll(() =>
  server.listen({
    onUnhandledRequest(request, print) {
      naoTratadas.push(`${request.method} ${request.url}`);
      print.error();
    },
  }),
);
afterEach(() => {
  server.resetHandlers();
  if (naoTratadas.length > 0) {
    const lista = naoTratadas.splice(0).join('\n  ');
    throw new Error(`Requisição sem handler no MSW — acrescente um handler no teste ou em src/test/setup.ts:\n  ${lista}`);
  }
});
afterAll(() => server.close());
