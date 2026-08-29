import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { TransactionSummary } from '../TransactionSummary';
import type { TransactionRead } from '@/types/transaction';

/**
 * O resumo do lançamento — a tela em que "quanto disso é meu?" é respondida.
 *
 * A divisão era listada como "**Fulano deve R$ 100**", e isso é falso na metade
 * dos casos: o rateio diz de quem é o CONSUMO, não quem está devendo. Quem pagou
 * a conta inteira aparecia "devendo" a própria parte quando, na verdade, tem a
 * receber — e quem lê o preview de uma despesa dividida vinha justamente saber
 * quanto daquilo é seu.
 */
vi.mock('@/hooks/use-auth', () => ({ useAuth: () => ({ user: { id: 1, name: 'Eu' } }) }));
vi.mock('@/hooks/use-members', () => ({
  useMembers: () => ({
    members: [
      { user_id: 1, user_name: 'Eu' },
      { user_id: 2, user_name: 'Ana' },
    ],
  }),
}));
vi.mock('@/hooks/use-payment-accounts', () => ({ usePaymentAccounts: () => ({ accounts: [] }) }));

const DIVIDIDA = {
  id: 1,
  workspace_id: 1,
  title: 'Jantar',
  currency: 'BRL',
  total_amount: '200.00',
  transaction_date: '2026-08-10T12:00:00Z',
  status: 'confirmed',
  payment_method: 'pix',
  payers: [{ id: 1, user_id: 1, amount: '200.00' }],
  splits: [
    { id: 1, user_id: 1, split_method: 'equal', input_value: '1', computed_amount: '100.00' },
    { id: 2, user_id: 2, split_method: 'equal', input_value: '1', computed_amount: '100.00' },
  ],
  items: [],
  adjustments: [],
  tags: [],
} as unknown as TransactionRead;

describe('TransactionSummary', () => {
  it('destaca a sua parte ao lado do valor cheio', () => {
    render(<TransactionSummary transaction={DIVIDIDA} />);
    const bloco = screen.getByText('Sua parte').closest('div')!;
    expect(within(bloco).getByText('R$ 100,00')).toBeInTheDocument();
    expect(within(bloco).getByText('de R$ 200,00')).toBeInTheDocument();
  });

  /*
   * Quem paga a conta inteira de uma despesa dividida TEM A RECEBER. Ler "Eu
   * devo R$ 100,00" logo abaixo de "Eu paguei R$ 200,00" é o inverso do que
   * aconteceu — e é o tipo de frase que faz alguém pagar duas vezes.
   */
  it('a divisão diz a parte de cada um, sem chamá-la de dívida', () => {
    render(<TransactionSummary transaction={DIVIDIDA} />);
    expect(screen.getByText(/Divisão — a parte de cada um/)).toBeInTheDocument();
    expect(screen.getByText('Você')).toBeInTheDocument();
    expect(screen.getByText('Ana')).toBeInTheDocument();
    expect(screen.queryByText(/deve/)).not.toBeInTheDocument();
  });

  /* Numa despesa de uma pessoa só, "Sua parte R$ 40,00 de R$ 40,00" repete o
     título do diálogo 40px acima e faz duvidar de qual é qual. */
  it('não repete a sua parte quando não há divisão', () => {
    render(
      <TransactionSummary
        transaction={{
          ...DIVIDIDA,
          total_amount: '40.00',
          splits: [
            { id: 1, user_id: 1, split_method: 'equal', input_value: '1', computed_amount: '40.00' },
          ],
        } as unknown as TransactionRead}
      />,
    );
    expect(screen.queryByText('Sua parte')).not.toBeInTheDocument();
  });
});
