import { renderHook } from '@testing-library/react';
import { useImports } from '../use-imports';
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

describe('useImports', () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = createTestQueryClient();
    useUIStore.getState().setCurrentWorkspaceId(1);
  });

  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

  it('should parse import data successfully', async () => {
    const workspaceId = 1;
    const mockFile = new File(['test'], 'test.csv', { type: 'text/csv' });
    
    server.use(
      http.post(`http://localhost:8000/api/v1/workspaces/${workspaceId}/imports/parse`, () => {
        return HttpResponse.json({
          rows: [
            { line: 2, title: 'CSV Tx', total_amount: 100.0, transaction_date: '2026-05-10' }
          ],
          skipped: [
            { line: 3, reason: 'data ou valor ausente' }
          ],
        });
      })
    );

    const { result } = renderHook(() => useImports(), { wrapper });

    const parsedData = await result.current.parse({
      file: mockFile,
      mapping: {
        date_column: 'Data',
        description_column: 'Descricao',
        amount_column: 'Valor',
        date_format: '%d/%m/%Y',
        delimiter: ';',
        decimal_separator: ',',
        invert_amount: true,
      },
    });

    expect(parsedData.rows).toHaveLength(1);
    expect(parsedData.rows[0].title).toBe('CSV Tx');
    expect(parsedData.skipped).toHaveLength(1);
    expect(parsedData.skipped[0].reason).toContain('ausente');
  });

  /*
   * O import era o ÚNICO hook de mutação do app sem invalidação local — 18 dos 19
   * invalidam no `onSuccess`, e `lib/ws-events.ts` escreve a regra em voz alta:
   * "sem depender da volta do evento pela rede".
   *
   * O defeito não é teórico. Com o WebSocket bloqueado por infra (proxy que não
   * faz upgrade) ou ainda em backoff, a pessoa importava o extrato inteiro, era
   * levada de volta ao Início e via os números de antes — sem nenhum sinal de que
   * faltava algo. As duas rotas de escrita são cobertas porque as duas tinham o
   * mesmo furo.
   */
  it.each([
    ['commit', (r: ReturnType<typeof useImports>) => r.commit({ filename: 'x.csv', rows: [] })],
    ['bulk', (r: ReturnType<typeof useImports>) => r.importTransactions([])],
  ])('invalida o cache local depois do %s, sem depender do WebSocket', async (rota, acao) => {
    server.use(
      http.post('http://localhost:8000/api/v1/workspaces/1/imports/commit', () =>
        HttpResponse.json({ batch_id: 1, imported: 2, ignored: 0, duplicate: 0, skipped: 0 }),
      ),
      http.post('http://localhost:8000/api/v1/workspaces/1/transactions/bulk', () =>
        HttpResponse.json({ status: 'ok', created: 2, skipped: 0, skipped_details: [] }),
      ),
    );

    // Cache "quente" com o estado ANTERIOR à importação, em duas famílias que o
    // ADR 0021 separa: uma do workspace e uma global.
    queryClient.setQueryData(['transactions', 1], { total: 0 });
    queryClient.setQueryData(['me-overview'], { total: 0 });
    expect(queryClient.getQueryState(['transactions', 1])?.isInvalidated).toBe(false);

    const { result } = renderHook(() => useImports(), { wrapper });
    await acao(result.current);

    expect(queryClient.getQueryState(['transactions', 1])?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(['me-overview'])?.isInvalidated).toBe(true);
    expect(rota).toBeTruthy();
  });
});
