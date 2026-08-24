import { renderHook, waitFor } from '@testing-library/react';
import { useDebts } from '../use-debts';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/setup';
import { describe, it, expect, beforeEach } from 'vitest';
import { useUIStore } from '@/stores';

const createTestQueryClient = () => new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
    },
  },
});

describe('useDebts', () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = createTestQueryClient();
    useUIStore.getState().setCurrentWorkspaceId(1);
  });

  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

  /*
   * A fixture daqui era ficção: `{id, title, total_amount, remaining_amount}` —
   * o formato de um FINANCIAMENTO, não de uma dívida entre membros. `/debts`
   * sempre devolveu `{debtor_id, creditor_id, amount}`, e o teste passava porque
   * a rota não declarava schema e o hook devolvia `any`: nem o `tsc` nem o teste
   * tinham como saber que a asserção era sobre um campo inexistente.
   *
   * É o defeito que tipar as rotas veio expor, e ele estava no próprio teste.
   */
  it('busca as dívidas do workspace atual', async () => {
    const workspaceId = 1;

    server.use(
      http.get(`http://localhost:8000/api/v1/workspaces/${workspaceId}/debts`, () => {
        // Valores como string decimal — a regra de `docs/API.md` para dinheiro.
        return HttpResponse.json([
          { debtor_id: 2, creditor_id: 1, amount: '150.00' },
        ]);
      })
    );

    const { result } = renderHook(() => useDebts(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.debts).toHaveLength(1);
    expect(result.current.debts[0]).toEqual({
      debtor_id: 2,
      creditor_id: 1,
      amount: '150.00',
    });
  });
});
