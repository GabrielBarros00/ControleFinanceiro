import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/setup';
import { describe, it, expect, beforeEach } from 'vitest';
import { TransactionHistory } from '../TransactionHistory';
import { ConfirmProvider } from '@/components/ui/confirm';
import { useAuthStore, useUIStore } from '@/stores';

const WS = 'http://localhost:8000/api/v1/workspaces/1';

const transaction = {
  id: 10,
  workspace_id: 1,
  title: 'Almoço',
  description: null,
  currency: 'BRL',
  total_amount: '50.00',
  transaction_date: '2026-07-15T12:00:00Z',
  billing_month: '2026-07',
  status: 'confirmed',
  split_mode: 'transaction',
  payment_method: 'pix',
  credit_card_id: null,
  statement_id: null,
  created_by_user_id: 1,
  created_at: '2026-07-15T12:00:00Z',
  updated_at: '2026-07-15T12:00:00Z',
  installment_no: null,
  installments_of: null,
  installment_group_id: null,
  payers: [{ id: 1, user_id: 1, amount: '50.00', payment_method: null, account_id: null }],
  splits: [{ id: 1, user_id: 1, split_method: 'equal', input_value: '100', computed_amount: '50.00' }],
  items: [],
  adjustments: [],
  tags: [],
};

// user id 1 (do /auth/me padrão) com o papel informado
function mockWorkspace(role: 'viewer' | 'member' | 'owner') {
  server.use(
    http.get(`${WS}/members`, () =>
      HttpResponse.json([
        { user_id: 1, role, user_name: 'Test User', user_email: 'test@example.com', joined_at: '2026-01-01' },
      ])
    ),
    http.get(`${WS}/categories`, () => HttpResponse.json([])),
    http.get(`${WS}/tags`, () => HttpResponse.json([])),
    http.get(`${WS}/transactions/`, () =>
      HttpResponse.json({ items: [transaction], total: 1, page: 1, limit: 10, total_pages: 1 })
    )
  );
}

function renderHistory() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ConfirmProvider>
        <TransactionHistory />
      </ConfirmProvider>
    </QueryClientProvider>
  );
}

describe('TransactionHistory — gate de RBAC (RBAC-FE-001)', () => {
  beforeEach(() => {
    useAuthStore.getState().setUser({ id: 1, name: 'Test User', email: 'test@example.com' });
    useUIStore.getState().setCurrentWorkspaceId(1);
  });

  it('desabilita editar/excluir para viewer', async () => {
    mockWorkspace('viewer');
    renderHistory();

    // Sem gate, os botões apareceriam habilitados: aqui devem permanecer travados
    const editBtn = await screen.findByLabelText('Editar transação');
    await waitFor(() => expect(editBtn).toBeDisabled());
    expect(screen.getByLabelText('Excluir transação')).toBeDisabled();
  });

  it('mantém editar/excluir habilitados para member', async () => {
    mockWorkspace('member');
    renderHistory();

    // Botão nasce travado (auth/members ainda carregando) e habilita ao resolver
    const editBtn = await screen.findByLabelText('Editar transação');
    await waitFor(() => expect(editBtn).not.toBeDisabled());
    expect(screen.getByLabelText('Excluir transação')).not.toBeDisabled();
  });
});
