import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, it, expect, beforeEach } from 'vitest';
import { server } from '@/test/setup';
import { useAuthStore } from '@/stores';
import { NotificationCenter } from '../NotificationCenter';

const API = 'http://localhost:8000/api/v1';

const wrapper = ({ children }: { children: React.ReactNode }) => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
};

const CONVITE = {
  id: 1,
  type: 'workspace_invite' as const,
  title: 'Ana convidou você para "Casa"',
  body: 'Você foi convidado como member.',
  workspace_id: 7,
  workspace_name: 'Casa',
  invite_token: 'tok-123',
  read_at: null,
  created_at: new Date().toISOString(),
};

function comNotificacoes(items: unknown[], unread: number) {
  server.use(
    http.get(`${API}/notifications`, () => HttpResponse.json({ items, unread })),
  );
}

describe('NotificationCenter', () => {
  beforeEach(() => {
    useAuthStore.setState({
      user: { id: 1, name: 'Eu', email: 'eu@x.com' },
      isAuthenticated: true,
      isLoading: false,
      error: null,
    });
  });

  it('mostra o contador de não lidas no sino', async () => {
    comNotificacoes([CONVITE], 1);
    render(<NotificationCenter />, { wrapper });

    const sino = await screen.findByRole('button', { name: /1 não lidas/i });
    expect(sino).toBeInTheDocument();
  });

  it('destaca convite pendente fora do painel — o sino sozinho é discreto demais', async () => {
    comNotificacoes([CONVITE], 1);
    render(<NotificationCenter />, { wrapper });

    expect(await screen.findByText(/Convite para "Casa" esperando resposta/i)).toBeInTheDocument();
  });

  it('oferece aceitar E recusar para um convite', async () => {
    comNotificacoes([CONVITE], 1);
    render(<NotificationCenter />, { wrapper });

    fireEvent.click(await screen.findByRole('button', { name: /notificações/i }));

    expect(await screen.findByRole('button', { name: /aceitar/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /recusar/i })).toBeInTheDocument();
  });

  it('recusar chama o endpoint de decline, não o de accept', async () => {
    comNotificacoes([CONVITE], 1);
    const chamadas: string[] = [];
    server.use(
      http.post(`${API}/invites/decline/:token`, ({ params }) => {
        chamadas.push(`decline:${params.token}`);
        return HttpResponse.json({ status: 'ok' });
      }),
      http.post(`${API}/invites/accept/:token`, ({ params }) => {
        chamadas.push(`accept:${params.token}`);
        return HttpResponse.json({ workspace_id: 7 });
      }),
    );

    render(<NotificationCenter />, { wrapper });
    fireEvent.click(await screen.findByRole('button', { name: /notificações/i }));
    fireEvent.click(await screen.findByRole('button', { name: /recusar/i }));

    await waitFor(() => expect(chamadas).toEqual(['decline:tok-123']));
  });

  it('sem notificações, não mostra contador nem faixa', async () => {
    comNotificacoes([], 0);
    render(<NotificationCenter />, { wrapper });

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Notificações' })).toBeInTheDocument(),
    );
    expect(screen.queryByText(/esperando resposta/i)).not.toBeInTheDocument();
  });
});
