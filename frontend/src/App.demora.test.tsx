import { act, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { delay, http, HttpResponse } from 'msw';
import { server } from '@/test/setup';
import App from './App';

/*
 * Arquivo próprio, e não `App.test.tsx`: o `App` tem um QueryClient de módulo, e
 * lá a sessão já teria sido carregada pelo teste vizinho — aqui ela tem de ficar
 * pendente do começo ao fim.
 */

afterEach(() => {
  vi.useRealTimers();
});

test('carregamento que passa do razoável diz isso e oferece recarregar', () => {
  /*
   * A tela do relato — "volto depois de um tempo e fica preta, como se
   * tentasse carregar" — era o "Carregando sua sessão…" sobre o fundo escuro,
   * sem prazo e sem botão. No app instalado não há recarregar do navegador à
   * vista; a pessoa só saía fechando o app.
   */
  server.use(
    http.get('http://localhost:8000/api/v1/auth/me', async () => {
      await delay('infinite');
      return HttpResponse.json({});
    }),
  );
  vi.useFakeTimers();

  render(<App />);
  expect(screen.getByText(/Carregando sua sessão/i)).toBeInTheDocument();
  expect(screen.queryByText(/demorando mais que o normal/i)).not.toBeInTheDocument();

  act(() => {
    vi.advanceTimersByTime(8_000);
  });

  expect(screen.getByText(/demorando mais que o normal/i)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Recarregar' })).toBeInTheDocument();
});
