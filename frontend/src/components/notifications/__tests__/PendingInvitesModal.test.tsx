import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, it, expect, beforeEach } from 'vitest';
import { server } from '@/test/setup';
import { useAuthStore } from '@/stores';
import { PendingInvitesModal } from '../PendingInvitesModal';

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

function comNotificacoes(items: unknown[], unread = items.length) {
  server.use(http.get(`${API}/notifications`, () => HttpResponse.json({ items, unread })));
}

function autenticar(needsOnboarding: boolean | undefined) {
  useAuthStore.setState({
    user: { id: 1, name: 'Eu', email: 'eu@x.com', needs_onboarding: needsOnboarding },
    isAuthenticated: true,
    isLoading: false,
    error: null,
  });
}

describe('PendingInvitesModal', () => {
  beforeEach(() => autenticar(false));

  it('apresenta o convite pendente como modal depois do onboarding', async () => {
    comNotificacoes([CONVITE]);
    render(<PendingInvitesModal />, { wrapper });

    const dialog = await screen.findByRole('dialog');
    expect(dialog).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Você foi convidado/ })).toBeInTheDocument();
    expect(screen.getByText(/Ana convidou você para "Casa"/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Aceitar/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Recusar/ })).toBeInTheDocument();
  });

  it('não aparece por cima do onboarding (needs_onboarding = true)', async () => {
    autenticar(true);
    comNotificacoes([CONVITE]);
    render(<PendingInvitesModal />, { wrapper });

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('não aparece quando não há convite pendente', async () => {
    comNotificacoes([{ ...CONVITE, read_at: new Date().toISOString() }], 0);
    render(<PendingInvitesModal />, { wrapper });

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('conta caso a conta antiga venha sem needs_onboarding', async () => {
    autenticar(undefined);
    comNotificacoes([CONVITE]);
    render(<PendingInvitesModal />, { wrapper });

    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });
});
