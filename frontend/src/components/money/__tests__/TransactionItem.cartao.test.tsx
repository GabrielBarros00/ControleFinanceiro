import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { TransactionItem } from '../TransactionItem';
import { paymentMethodWithCard } from '@/lib/payment-methods';
import type { TransactionRead } from '@/types/transaction';

/*
 * Qual cartão pagou a compra.
 *
 * A linha e o detalhe diziam só "Cartão de crédito". Quem tem mais de um cartão
 * não via em qual a compra caiu e achou que o cartão não tinha sido gravado (ele
 * estava: `credit_card_id` e a fatura). O nome vem dos cartões da própria pessoa;
 * o de outro membro é pessoal dele e continua genérico.
 */
const CARTOES = [{ id: 1, name: 'Nubank' }, { id: 2, name: 'C6 Bank' }];

const tx: TransactionRead = {
  id: 231, workspace_id: 1, title: 'Coca lata', description: null, currency: 'BRL', total_amount: '6.00',
  transaction_date: '2026-09-24T12:00:00Z', billing_month: '2026-09', status: 'confirmed',
  credit_card_id: 2, statement_id: 16, split_mode: 'transaction', payment_method: 'credit_card',
  installment_no: null, installments_of: null, installment_group_id: null, created_by_user_id: 1,
  created_at: '2026-09-24T12:00:00Z', updated_at: '2026-09-24T12:00:00Z',
  payers: [{ id: 1, user_id: 1, amount: '6.00', payment_method: null, account_id: null }],
  splits: [{ id: 1, user_id: 1, split_method: 'equal', input_value: '100', computed_amount: '6.00' }],
  items: [], adjustments: [], tags: [],
};

describe('forma de pagamento com o cartão', () => {
  it('diz qual cartão quando ele é da pessoa', () => {
    expect(paymentMethodWithCard('credit_card', 2, CARTOES)).toBe('Cartão C6 Bank');
  });

  it('cartão de outra pessoa (fora da lista) continua "Cartão de crédito"', () => {
    expect(paymentMethodWithCard('credit_card', 99, CARTOES)).toBe('Cartão de crédito');
  });

  it('fora do cartão, a forma de sempre', () => {
    expect(paymentMethodWithCard('pix', null, CARTOES)).toBe('Pix');
    expect(paymentMethodWithCard(null, null, CARTOES)).toBe('—');
  });

  it('a linha da lista mostra o cartão', () => {
    render(<TransactionItem tx={tx} cardName="C6 Bank" />);
    expect(screen.getByText(/Cartão C6 Bank/)).toBeInTheDocument();
    expect(screen.queryByText(/Cartão de crédito/)).not.toBeInTheDocument();
  });

  it('sem o nome (cartão de outro membro), a linha continua genérica', () => {
    render(<TransactionItem tx={tx} />);
    expect(screen.getByText(/Cartão de crédito/)).toBeInTheDocument();
  });
});
