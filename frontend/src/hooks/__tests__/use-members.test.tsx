import React from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { describe, it, expect, beforeEach } from 'vitest';
import { server } from '@/test/setup';
import { useMembers } from '../use-members';
import { useUIStore } from '@/stores';

const wrapper = ({ children }: { children: React.ReactNode }) => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
};

describe('useMembers', () => {
  beforeEach(() => {
    useUIStore.getState().setCurrentWorkspaceId(1);
  });

  it('lista membros do workspace atual', async () => {
    server.use(
      http.get('http://localhost:8000/api/v1/workspaces/1/members', () =>
        HttpResponse.json([
          { user_id: 1, role: 'owner', user_name: 'Ana', user_email: 'ana@x.com', joined_at: '2026-01-01' },
          { user_id: 2, role: 'member', user_name: 'Bia', user_email: 'bia@x.com', joined_at: '2026-01-02' },
        ])
      ),
      http.get('http://localhost:8000/api/v1/workspaces/1/invites', () => HttpResponse.json([])),
    );

    const { result } = renderHook(() => useMembers(), { wrapper });

    await waitFor(() => expect(result.current.members).toHaveLength(2));
    expect(result.current.members[0].user_name).toBe('Ana');
    expect(result.current.members[1].role).toBe('member');
  });

  it('convida por email', async () => {
    let sentBody: Record<string, unknown> | null = null;
    server.use(
      http.get('http://localhost:8000/api/v1/workspaces/1/members', () => HttpResponse.json([])),
      http.get('http://localhost:8000/api/v1/workspaces/1/invites', () => HttpResponse.json([])),
      http.post('http://localhost:8000/api/v1/workspaces/1/invites', async ({ request }) => {
        sentBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ status: 'invite_sent' });
      }),
    );

    const { result } = renderHook(() => useMembers(), { wrapper });
    const res = await result.current.inviteByEmail({ email: 'novo@x.com', role: 'viewer' });

    expect(res.status).toBe('invite_sent');
    expect(sentBody).toEqual({ email: 'novo@x.com', role: 'viewer' });
  });
});
