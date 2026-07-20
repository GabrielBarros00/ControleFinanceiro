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

  it('should fetch debts for the current workspace', async () => {
    const workspaceId = 1;
    
    server.use(
      http.get(`http://localhost:8000/api/v1/workspaces/${workspaceId}/debts`, () => {
        return HttpResponse.json([
          { id: 1, title: 'Car Loan', total_amount: 50000, remaining_amount: 45000 }
        ]);
      })
    );

    const { result } = renderHook(() => useDebts(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.debts).toHaveLength(1);
    expect(result.current.debts[0].title).toBe('Car Loan');
  });
});
