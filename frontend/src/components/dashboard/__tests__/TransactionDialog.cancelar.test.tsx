import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/setup';
import { useAuthStore, useUIStore } from '@/stores';
import { ConfirmProvider } from '@/components/ui/confirm';
import type { TransactionRead } from '@/types/transaction';
import { TransactionDialog } from '../TransactionDialog';

/**
 * Cancelar um lançamento pela tela.
 *
 * O agente de IA cancelava (`status=cancelled`: continua visível e deixa de
 * contar), a tela só sabia excluir. E o lançamento cancelado abria o formulário
 * de edição como qualquer outro, que só descobria no "Salvar" que o servidor
 * recusa editar o que está cancelado.
 */
const tx: TransactionRead = {
  id: 50, workspace_id: 1, title: 'Show', currency: 'BRL', total_amount: '200.00',
  transaction_date: '2026-09-20T15:00:00Z', billing_month: '2026-09', status: 'confirmed',
  credit_card_id: null, split_mode: 'transaction', payment_method: 'pix',
  created_by_user_id: 1, created_at: '', updated_at: '', tags: [], adjustments: [], items: [],
  payers: [{ id: 1, user_id: 1, amount: '200.00' }],
  splits: [{ id: 1, user_id: 1, split_method: 'equal', input_value: '0', computed_amount: '200.00' }],
};

function renderizar(t: TransactionRead, onCancel = vi.fn(), inteira: TransactionRead | null = null) {
  useUIStore.getState().setCurrentWorkspaceId(1);
  useAuthStore.getState().setUser({ id: 1, name: 'Alice', email: 'alice@t.com' });
  server.use(
    http.get('http://localhost:8000/api/v1/workspaces/1/members', () => HttpResponse.json([
      { user_id: 1, role: 'owner', user_name: 'Alice', user_email: 'alice@t.com', joined_at: '2026-01-01' },
    ])),
    http.get('http://localhost:8000/api/v1/workspaces/1/invites', () => HttpResponse.json([])),
    http.get('http://localhost:8000/api/v1/workspaces/1/categories', () => HttpResponse.json([])),
    http.get('http://localhost:8000/api/v1/workspaces/1/tags', () => HttpResponse.json([])),
    http.get('http://localhost:8000/api/v1/me/credit-cards/', () => HttpResponse.json([])),
    http.get('http://localhost:8000/api/v1/workspaces/1/transactions/:id/attachments', () => HttpResponse.json([])),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ConfirmProvider>
        <TransactionDialog
          transaction={t} open onOpenChange={() => {}} onSave={vi.fn()} onDelete={vi.fn()} onCancel={onCancel}
          installmentWhole={inteira}
        />
      </ConfirmProvider>
    </QueryClientProvider>,
  );
  return onCancel;
}

describe('TransactionDialog — cancelar', () => {
  it('a zona de perigo oferece cancelar, além de excluir', () => {
    const onCancel = renderizar(tx);
    fireEvent.click(screen.getByRole('button', { name: /Cancelar lançamento/ }));
    expect(onCancel).toHaveBeenCalledWith(50);
  });

  it('na compra parcelada, cancelar é a compra inteira', () => {
    const parcela = { ...tx, installments_of: 3, installment_no: 1, installment_group_id: 'g1' };
    const onCancel = renderizar(parcela, vi.fn(), { ...parcela, total_amount: '600.00' });
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar a compra (parcelas em aberto)' }));
    expect(onCancel).toHaveBeenCalledWith(50);
  });

  it('o lançamento cancelado abre só leitura, dizendo o que aconteceu', () => {
    renderizar({ ...tx, status: 'cancelled' });
    expect(screen.getByText('Lançamento cancelado')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Salvar Alterações' })).toBeNull();
    expect(screen.queryByRole('button', { name: /Cancelar lançamento/ })).toBeNull();
  });
});
