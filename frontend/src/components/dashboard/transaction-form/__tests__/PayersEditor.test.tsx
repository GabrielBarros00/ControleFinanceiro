import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/setup';
import { describe, it, expect, beforeEach } from 'vitest';
import { NewTransactionDialog } from '../../NewTransactionDialog';
import { useAuthStore, useUIStore } from '@/stores';

const WS = 'http://localhost:8000/api/v1/workspaces/1';

const members = [
  { user_id: 1, role: 'owner', user_name: 'Alice', user_email: 'alice@t.com', joined_at: '2026-01-01' },
  { user_id: 2, role: 'member', user_name: 'Bob', user_email: 'bob@t.com', joined_at: '2026-01-01' },
];

function renderForm() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <NewTransactionDialog open onOpenChange={() => {}} />
    </QueryClientProvider>
  );
}

describe('PayersEditor — múltiplos pagadores', () => {
  beforeEach(() => {
    useAuthStore.getState().setUser({ id: 1, name: 'Alice', email: 'alice@t.com' });
    useUIStore.getState().setCurrentWorkspaceId(1);
    server.use(
      http.get(`${WS}/members`, () => HttpResponse.json(members)),
      http.get(`${WS}/invites`, () => HttpResponse.json([])),
      http.get(`${WS}/categories`, () => HttpResponse.json([])),
      http.get(`${WS}/credit-cards/`, () => HttpResponse.json([])),
      http.get(`${WS}/tags`, () => HttpResponse.json([])),
    );
  });

  it('com um pagador não exibe input de valor (paga o total implícito)', async () => {
    renderForm();
    await screen.findAllByText('Alice');
    expect(screen.queryAllByLabelText('Valor pago')).toHaveLength(0);
  });

  it('bloqueia submit quando pagadores não fecham o total', async () => {
    let createCalled = false;
    server.use(
      http.post(`${WS}/transactions/`, () => {
        createCalled = true;
        return HttpResponse.json({ id: 1 });
      })
    );
    renderForm();
    await screen.findAllByText('Alice');

    fireEvent.change(screen.getByLabelText('Título / Descrição'), { target: { value: 'Mercado' } });
    fireEvent.change(screen.getByLabelText('Valor Total'), { target: { value: '90,00' } });

    fireEvent.click(screen.getByRole('button', { name: '+ Pagador' }));
    const paidInputs = await screen.findAllByLabelText('Valor pago');
    fireEvent.change(screen.getByLabelText('Pagador'), { target: { value: '2' } });
    fireEvent.change(paidInputs[0], { target: { value: '50,00' } });
    fireEvent.change(paidInputs[1], { target: { value: '30,00' } });

    fireEvent.click(screen.getByRole('button', { name: 'Salvar Despesa' }));

    await screen.findAllByText(/pagadores somam/i);
    expect(createCalled).toBe(false);
  });

  it('envia os valores de cada pagador quando a soma fecha', async () => {
    let payload: Record<string, unknown> | null = null;
    server.use(
      http.post(`${WS}/transactions/`, async ({ request }) => {
        payload = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: 1, ...payload });
      })
    );
    renderForm();
    await screen.findAllByText('Alice');

    fireEvent.change(screen.getByLabelText('Título / Descrição'), { target: { value: 'Mercado' } });
    fireEvent.change(screen.getByLabelText('Valor Total'), { target: { value: '90,00' } });

    fireEvent.click(screen.getByRole('button', { name: '+ Pagador' }));
    const paidInputs = await screen.findAllByLabelText('Valor pago');
    fireEvent.change(screen.getByLabelText('Pagador'), { target: { value: '2' } });
    fireEvent.change(paidInputs[0], { target: { value: '50,00' } });
    fireEvent.change(paidInputs[1], { target: { value: '40,00' } });

    fireEvent.click(screen.getByRole('button', { name: 'Salvar Despesa' }));

    await waitFor(() => expect(payload).not.toBeNull());
    expect(payload!.payers).toEqual([
      { user_id: 1, amount: 50, payment_method: null, account_id: null },
      { user_id: 2, amount: 40, payment_method: null, account_id: null },
    ]);
  });
});
