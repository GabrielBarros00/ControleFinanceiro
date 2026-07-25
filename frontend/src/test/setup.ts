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
  })
];

export const server = setupServer(...handlers);

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
