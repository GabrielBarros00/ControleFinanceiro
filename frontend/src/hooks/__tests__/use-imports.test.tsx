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
});
