import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as React from 'react';
import { useTransactions } from '../use-transactions';

/**
 * Todo filtro tem de chegar aos DOIS lugares: a `queryKey` e os `params`.
 *
 * Esquecer um dos dois falha em SILÊNCIO, e os dois sintomas se parecem com "o
 * filtro não funciona": fora da chave, mudar o valor não refaz a consulta e a
 * lista fica congelada; fora dos `params`, o backend devolve tudo e o controle
 * na tela vira decoração. Nenhum dos dois quebra tipo, e foi exatamente o que
 * aconteceu quando `settled` (ADR 0029) foi acrescentado à interface.
 */
const mockGet = vi.hoisted(() => vi.fn());

vi.mock('@/api/client', () => ({
  apiClient: { get: mockGet, post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));
vi.mock('../use-workspace-id', () => ({ useWorkspaceId: () => 7 }));

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  mockGet.mockReset();
  mockGet.mockResolvedValue({
    data: { items: [], total: 0, total_amount: '0', page: 1, limit: 10, total_pages: 1 },
  });
});

describe('useTransactions — os filtros chegam à API', () => {
  it('manda `settled: false` quando o recorte é "só a pagar"', async () => {
    renderHook(() => useTransactions({ page: 1, limit: 10, settled: false }), { wrapper });

    await waitFor(() => expect(mockGet).toHaveBeenCalled());
    // `false`, e não `undefined`: com `|| undefined` no lugar de `?? undefined`
    // o recorte "só a pagar" viraria "sem filtro" e a lista mostraria tudo.
    expect(mockGet.mock.calls[0][1].params).toMatchObject({ settled: false });
  });

  it('não manda o campo quando não há recorte', async () => {
    renderHook(() => useTransactions({ page: 1, limit: 10 }), { wrapper });

    await waitFor(() => expect(mockGet).toHaveBeenCalled());
    expect(mockGet.mock.calls[0][1].params.settled).toBeUndefined();
  });

  it('"Sem categoria" chega ao servidor e refaz a consulta', async () => {
    // O seletor de categoria da tela oferecia "Sem categoria" (e o link dos
    // Relatórios apontava para ele), mas o hook não mandava o campo: a lista
    // mostrava tudo, e o recorte era só decoração.
    const { rerender } = renderHook(
      ({ uncategorized }: { uncategorized?: boolean }) => useTransactions({ page: 1, limit: 10, uncategorized }),
      { wrapper, initialProps: {} as { uncategorized?: boolean } },
    );
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(1));
    expect(mockGet.mock.calls[0][1].params.uncategorized).toBeUndefined();

    rerender({ uncategorized: true });
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));
    expect(mockGet.mock.calls[1][1].params).toMatchObject({ uncategorized: true });
  });

  it('o estabelecimento chega ao servidor e refaz a consulta', async () => {
    const { rerender } = renderHook(
      ({ merchant_id }: { merchant_id?: number }) => useTransactions({ page: 1, limit: 10, merchant_id }),
      { wrapper, initialProps: {} as { merchant_id?: number } },
    );
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(1));
    rerender({ merchant_id: 4 });
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));
    expect(mockGet.mock.calls[1][1].params).toMatchObject({ merchant_id: 4 });
  });

  it('trocar o recorte refaz a consulta (o filtro está na queryKey)', async () => {
    const { rerender } = renderHook(
      ({ settled }: { settled?: boolean }) =>
        useTransactions({ page: 1, limit: 10, settled }),
      { wrapper, initialProps: {} as { settled?: boolean } },
    );
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(1));

    rerender({ settled: false });
    // Sem `settled` na chave, o TanStack devolveria o cache da consulta anterior
    // e a lista ficaria congelada no recorte antigo.
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));
  });
});
