import React from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { server } from '@/test/setup';
import { useAuthStore } from '@/stores';
import { useReportCurrency, useSetReportCurrency } from '../use-report-currency';

/*
 * A moeda de relatório vem da SESSÃO (auditoria 2026-09-26, P6). Antes o hook
 * buscava o `/me/overview` inteiro só para ler o campo `currency`.
 */
describe('useReportCurrency', () => {
  let queryClient: QueryClient;
  let pedidosAoOverview = 0;
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

  beforeEach(() => {
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    pedidosAoOverview = 0;
    server.use(http.get('http://localhost:8000/api/v1/me/overview', () => {
      pedidosAoOverview += 1;
      return HttpResponse.json({ currency: 'EUR' });
    }));
  });

  afterEach(() => useAuthStore.getState().logout());

  it('lê a moeda da sessão, sem requisição nenhuma', async () => {
    useAuthStore.getState().setUser({ id: 1, name: 'A', email: 'a@t.com', report_currency: 'USD' });
    const { result } = renderHook(() => useReportCurrency(), { wrapper });
    expect(result.current).toBe('USD');
    await new Promise((ok) => setTimeout(ok, 50));
    expect(pedidosAoOverview).toBe(0);
  });

  it('sem sessão (ou sessão antiga, sem o campo), cai em BRL', () => {
    useAuthStore.getState().setUser({ id: 1, name: 'A', email: 'a@t.com' });
    const { result } = renderHook(() => useReportCurrency(), { wrapper });
    expect(result.current).toBe('BRL');
  });

  it('trocar a moeda atualiza a sessão e o cache da auth-me', async () => {
    server.use(http.patch('http://localhost:8000/api/v1/me/report-currency', () =>
      HttpResponse.json({ report_currency: 'EUR' })));
    useAuthStore.getState().setUser({ id: 1, name: 'A', email: 'a@t.com', report_currency: 'BRL' });
    queryClient.setQueryData(['auth-me'], { id: 1, name: 'A', email: 'a@t.com', report_currency: 'BRL' });

    const { result } = renderHook(() => ({ moeda: useReportCurrency(), trocar: useSetReportCurrency() }), { wrapper });
    await act(async () => { await result.current.trocar.mutateAsync('EUR'); });

    await waitFor(() => expect(result.current.moeda).toBe('EUR'));
    expect(queryClient.getQueryData<{ report_currency: string }>(['auth-me'])?.report_currency).toBe('EUR');
  });
});
