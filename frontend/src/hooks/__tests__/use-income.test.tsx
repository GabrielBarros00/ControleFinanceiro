import React from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { describe, it, expect, beforeEach } from 'vitest';
import { server } from '@/test/setup';
import { useIncome } from '../use-income';
import { useUIStore } from '@/stores';

const wrapper = ({ children }: { children: React.ReactNode }) => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
};

describe('useIncome', () => {
  beforeEach(() => {
    useUIStore.getState().setCurrentWorkspaceId(1);
  });

  it('lista as rendas do workspace atual', async () => {
    server.use(
      http.get('http://localhost:8000/api/v1/workspaces/1/income/', () =>
        HttpResponse.json([
          { id: 1, title: 'Salário', amount: '5000.00', received_at: '2026-07-01T12:00:00', user_id: 1 },
          { id: 2, title: 'Freela', amount: '1200.00', received_at: '2026-07-05T12:00:00', user_id: 1 },
        ])
      ),
    );

    const { result } = renderHook(() => useIncome(), { wrapper });

    await waitFor(() => expect(result.current.incomes).toHaveLength(2));
    expect(result.current.incomes[0].title).toBe('Salário');
  });

  it('cria uma renda', async () => {
    let sentBody: Record<string, unknown> | null = null;
    server.use(
      http.get('http://localhost:8000/api/v1/workspaces/1/income/', () => HttpResponse.json([])),
      http.post('http://localhost:8000/api/v1/workspaces/1/income/', async ({ request }) => {
        sentBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: 3, ...sentBody, user_id: 1 });
      }),
    );

    const { result } = renderHook(() => useIncome(), { wrapper });
    const created = await result.current.create({
      title: 'Bônus',
      amount: 800,
      received_at: '2026-07-10T12:00:00.000Z',
    });

    expect(created.id).toBe(3);
    expect(sentBody!.title).toBe('Bônus');
    expect(sentBody!.amount).toBe(800);
  });
});
