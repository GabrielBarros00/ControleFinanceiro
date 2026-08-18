import { renderHook, waitFor } from '@testing-library/react';
import { useTransactions } from '../use-transactions';
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

describe('useTransactions', () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = createTestQueryClient();
    // Set workspace ID in store
    useUIStore.getState().setCurrentWorkspaceId(1);
  });

  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

  it('should fetch transactions for the current workspace', async () => {
    const workspaceId = 1;
    
    server.use(
      http.get(`http://localhost:8000/api/v1/workspaces/${workspaceId}/transactions/`, () => {
        return HttpResponse.json({
          items: [
            { id: 1, title: 'Test Tx', total_amount: 100.0, transaction_date: '2026-05-10T00:00:00' }
          ],
          total: 1,
          page: 1,
          limit: 10,
          total_pages: 1
        });
      })
    );

    const { result } = renderHook(() => useTransactions(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.transactions).toHaveLength(1);
    expect(result.current.transactions[0].title).toBe('Test Tx');
  });

  it('should create a transaction and refetch', async () => {
    const workspaceId = 1;
    let createCalled = false;

    server.use(
      http.post(`http://localhost:8000/api/v1/workspaces/${workspaceId}/transactions/`, () => {
        createCalled = true;
        return HttpResponse.json({ id: 2, title: 'New Tx' });
      }),
      http.get(`http://localhost:8000/api/v1/workspaces/${workspaceId}/transactions/`, () => {
        return HttpResponse.json({
            items: createCalled ? [{ id: 2, title: 'New Tx', total_amount: 50.0, transaction_date: '2026-05-10T00:00:00' }] : [],
            total: createCalled ? 1 : 0,
            page: 1,
            limit: 10,
            total_pages: 1
        });
      })
    );

    const { result } = renderHook(() => useTransactions(), { wrapper });

    // Payload MÍNIMO válido: `transaction_date` e `payers` são obrigatórios de
    // verdade no contrato — o resto tem default no servidor. Antes, com o corpo
    // tipado como `Record<string, unknown>`, este teste passava enviando algo que
    // a API recusaria com 422.
    await result.current.create({
      title: 'New Tx',
      total_amount: 50.0,
      transaction_date: '2026-05-10T12:00:00Z',
      payers: [{ user_id: 1, amount: 50.0 }],
    });
    
    expect(createCalled).toBe(true);
    
    await waitFor(() => {
        expect(result.current.transactions).toHaveLength(1);
    });
  });

  it('should update a transaction and refetch', async () => {
    const workspaceId = 1;
    const txId = 2;
    let updateCalled = false;

    server.use(
      http.put(`http://localhost:8000/api/v1/workspaces/${workspaceId}/transactions/${txId}`, () => {
        updateCalled = true;
        return HttpResponse.json({ id: txId, title: 'Updated Tx' });
      }),
      http.get(`http://localhost:8000/api/v1/workspaces/${workspaceId}/transactions/`, () => {
        return HttpResponse.json({
            items: updateCalled ? [{ id: txId, title: 'Updated Tx', total_amount: 50.0, transaction_date: '2026-05-10T00:00:00' }] : [{ id: txId, title: 'Old Tx' }],
            total: 1,
            page: 1,
            limit: 10,
            total_pages: 1
        });
      })
    );

    const { result } = renderHook(() => useTransactions(), { wrapper });

    await result.current.update({ id: txId, data: { title: 'Updated Tx' } });
    
    expect(updateCalled).toBe(true);
    
    await waitFor(() => {
        expect(result.current.transactions[0].title).toBe('Updated Tx');
    });
  });

  it('should delete a transaction and refetch', async () => {
    const workspaceId = 1;
    const txId = 2;
    let deleteCalled = false;

    server.use(
      http.delete(`http://localhost:8000/api/v1/workspaces/${workspaceId}/transactions/${txId}`, () => {
        deleteCalled = true;
        return new HttpResponse(null, { status: 204 });
      }),
      http.get(`http://localhost:8000/api/v1/workspaces/${workspaceId}/transactions/`, () => {
        return HttpResponse.json({
            items: deleteCalled ? [] : [{ id: txId, title: 'To Be Deleted' }],
            total: deleteCalled ? 0 : 1,
            page: 1,
            limit: 10,
            total_pages: 1
        });
      })
    );

    const { result } = renderHook(() => useTransactions(), { wrapper });

    await result.current.remove(txId);
    
    expect(deleteCalled).toBe(true);
    
    await waitFor(() => {
        expect(result.current.transactions).toHaveLength(0);
    });
  });
});
