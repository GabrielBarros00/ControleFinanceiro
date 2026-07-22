import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { TransactionItem } from '../TransactionItem';
import type { TransactionRead } from '@/types/transaction';

/*
 * RBAC-FE-001: viewer não edita/exclui. Antes vivia em TransactionHistory (removido);
 * agora o gate é do TransactionItem via prop canWrite, testado aqui na unidade.
 */
const tx: TransactionRead = {
  id: 10,
  workspace_id: 1,
  title: 'Almoço',
  description: null,
  currency: 'BRL',
  total_amount: '50.00',
  transaction_date: '2026-07-15T12:00:00Z',
  billing_month: '2026-07',
  status: 'confirmed',
  credit_card_id: null,
  statement_id: null,
  split_mode: 'transaction',
  payment_method: 'pix',
  installment_no: null,
  installments_of: null,
  installment_group_id: null,
  created_by_user_id: 1,
  created_at: '2026-07-15T12:00:00Z',
  updated_at: '2026-07-15T12:00:00Z',
  payers: [{ id: 1, user_id: 1, amount: '50.00', payment_method: null, account_id: null }],
  splits: [{ id: 1, user_id: 1, split_method: 'equal', input_value: '100', computed_amount: '50.00' }],
  items: [],
  adjustments: [],
  tags: [],
};

describe('TransactionItem — gate de RBAC (RBAC-FE-001)', () => {
  it('desabilita editar/excluir para viewer (canWrite=false)', () => {
    render(<TransactionItem tx={tx} canWrite={false} onEdit={() => {}} onDelete={() => {}} />);
    expect(screen.getByLabelText('Editar transação')).toBeDisabled();
    expect(screen.getByLabelText('Excluir transação')).toBeDisabled();
  });

  it('mantém editar/excluir habilitados para quem pode escrever (canWrite=true)', () => {
    render(<TransactionItem tx={tx} canWrite onEdit={() => {}} onDelete={() => {}} />);
    expect(screen.getByLabelText('Editar transação')).not.toBeDisabled();
    expect(screen.getByLabelText('Excluir transação')).not.toBeDisabled();
  });
});
