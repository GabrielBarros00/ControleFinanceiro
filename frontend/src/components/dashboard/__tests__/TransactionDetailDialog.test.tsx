import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/setup';
import { useUIStore } from '@/stores';
import type { TransactionRead } from '@/types/transaction';
import { TransactionDetailDialog } from '../TransactionDetailDialog';

/**
 * O detalhe do lançamento mostra a observação e QUAL cartão pagou.
 *
 * A observação existia (a IA a preenchia), mas nenhuma tela a mostrava; e o
 * cartão aparecia só como "Cartão de crédito".
 */
const tx: TransactionRead = {
  id: 231, workspace_id: 1, title: 'Coca lata', description: 'Coca lata comprada na Duff\nsem gelo', currency: 'BRL',
  total_amount: '5.70', transaction_date: '2026-09-24T15:00:00Z', billing_month: '2026-09', status: 'confirmed',
  credit_card_id: 2, statement_id: 16, split_mode: 'transaction', payment_method: 'credit_card',
  created_by_user_id: 1, created_at: '', updated_at: '', tags: [], adjustments: [], items: [],
  payers: [{ id: 1, user_id: 1, amount: '5.70' }],
  splits: [{ id: 1, user_id: 1, split_method: 'equal', input_value: '0', computed_amount: '5.70' }],
};

function renderizar(t: TransactionRead) {
  useUIStore.getState().setCurrentWorkspaceId(1);
  server.use(
    http.get('http://localhost:8000/api/v1/me/credit-cards/', () => HttpResponse.json([{ id: 2, name: 'C6 Bank' }])),
    http.get('http://localhost:8000/api/v1/workspaces/1/categories', () => HttpResponse.json([])),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <TransactionDetailDialog transaction={t} open onOpenChange={() => {}} />
    </QueryClientProvider>,
  );
}

describe('TransactionDetailDialog', () => {
  it('mostra a observação, com a quebra de linha, e o nome do cartão', async () => {
    renderizar(tx);
    expect(screen.getByText(/Coca lata comprada na Duff/)).toHaveClass('whitespace-pre-wrap');
    expect(await screen.findByText(/Cartão C6 Bank/)).toBeInTheDocument();
  });

  it('sem observação, não desenha a caixa vazia', () => {
    renderizar({ ...tx, description: null });
    expect(screen.queryByText(/comprada na Duff/)).not.toBeInTheDocument();
  });
});
