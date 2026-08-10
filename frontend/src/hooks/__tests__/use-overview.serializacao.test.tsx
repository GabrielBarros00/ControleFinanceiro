import React from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { describe, it, expect } from 'vitest';
import { server } from '@/test/setup';
import { useLedger } from '../use-overview';

/**
 * A SERIALIZAÇÃO dos filtros, não o formato deles.
 *
 * O Extrato global tinha um teste que mockava `useLedger` e afirmava que o hook
 * recebeu `source: ['income']`. Ele passava — e o filtro não funcionava. O Axios
 * serializa array como `source[]=income` por padrão, o FastAPI espera parâmetros
 * REPETIDOS (`source=income&source=statement_payment`), e um parâmetro que ele
 * não reconhece é ignorado em silêncio: 200, mês inteiro, botão marcado.
 *
 * Por isso a asserção aqui é sobre a URL que saiu na rede. É a única camada em
 * que esse defeito é visível.
 */
const RESPOSTA = {
  currency: 'BRL',
  month: '2026-07',
  total: 0,
  cash_in: '0.00',
  cash_out: '0.00',
  net_cash: '0.00',
  excluded_foreign_count: 0,
  entries: [],
};

const wrapper = ({ children }: { children: React.ReactNode }) => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
};

function capturarUrl() {
  const capturada: { valor: string | null } = { valor: null };
  server.use(
    http.get('http://localhost:8000/api/v1/me/ledger', ({ request }) => {
      capturada.valor = request.url;
      return HttpResponse.json(RESPOSTA);
    }),
  );
  return capturada;
}

describe('useLedger — serialização dos filtros', () => {
  it('manda origens como parâmetros repetidos, sem colchetes', async () => {
    const url = capturarUrl();

    const { result } = renderHook(
      () => useLedger({ month: '2026-07', source: ['income', 'statement_payment'] }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    const params = new URL(url.valor!).searchParams;
    expect(params.getAll('source')).toEqual(['income', 'statement_payment']);
    // O sintoma exato do defeito: o backend não lê `source[]` e devolve o mês
    // inteiro como se nenhum filtro tivesse sido pedido.
    expect(url.valor).not.toContain('source%5B%5D');
    expect(url.valor).not.toContain('source[]');
  });

  it('uma origem só também vai como `source=`', async () => {
    const url = capturarUrl();

    const { result } = renderHook(() => useLedger({ source: ['income'] }), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(new URL(url.valor!).searchParams.getAll('source')).toEqual(['income']);
  });

  it('sem filtro de origem, o parâmetro não aparece', async () => {
    const url = capturarUrl();

    const { result } = renderHook(() => useLedger({ month: '2026-07' }), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    const params = new URL(url.valor!).searchParams;
    expect(params.getAll('source')).toEqual([]);
    expect(params.get('month')).toBe('2026-07');
  });
});
