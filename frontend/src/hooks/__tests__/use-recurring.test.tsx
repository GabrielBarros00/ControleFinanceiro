import { renderHook, waitFor } from '@testing-library/react';
import { useRecurring } from '../use-recurring';
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

describe('useRecurring', () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = createTestQueryClient();
    useUIStore.getState().setCurrentWorkspaceId(1);
  });

  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

  it('should fetch recurring expenses', async () => {
    const workspaceId = 1;
    
    server.use(
      http.get(`http://localhost:8000/api/v1/workspaces/${workspaceId}/recurring`, () => {
        return HttpResponse.json([
          { id: 1, title: 'Netflix', base_amount: 55.9, day_of_month: 15, is_active: true }
        ]);
      })
    );

    const { result } = renderHook(() => useRecurring(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.recurring).toHaveLength(1);
    expect(result.current.recurring[0].title).toBe('Netflix');
  });

  it('should create a recurring expense', async () => {
    const workspaceId = 1;
    let created = false;

    server.use(
      http.post(`http://localhost:8000/api/v1/workspaces/${workspaceId}/recurring`, () => {
        created = true;
        return HttpResponse.json({ id: 2, title: 'Spotify' });
      }),
      http.get(`http://localhost:8000/api/v1/workspaces/${workspaceId}/recurring`, () => {
        return HttpResponse.json(created ? [{ id: 2, title: 'Spotify' }] : []);
      })
    );

    const { result } = renderHook(() => useRecurring(), { wrapper });

    await result.current.create({ title: 'Spotify', base_amount: 21.9, day_of_month: 1 });
    
    expect(created).toBe(true);
    await waitFor(() => expect(result.current.recurring).toHaveLength(1));
  });
});
