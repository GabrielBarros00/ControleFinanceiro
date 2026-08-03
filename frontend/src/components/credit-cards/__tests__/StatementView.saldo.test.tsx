import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { StatementView } from '../StatementView';

/**
 * Fatura com SALDO pendente (P0 da auditoria).
 *
 * O backend aceitava qualquer valor e marcava a fatura como paga do mesmo jeito
 * — R$ 1 numa fatura de R$ 1.000 devolvia `paid` e liberava o limite inteiro. E
 * a tela ajudava: o diálogo mandava só `account_id`, sem valor, e a copy dizia
 * "o valor pago é o total fechado da fatura". Agora o saldo é cumulativo, e a
 * tela precisa mostrá-lo e deixar pagar por partes.
 */
const pay = vi.fn();

const FATURA_PARCIAL = {
  id: 10,
  card_id: 1,
  month: '2026-07',
  status: 'closed',
  closing_date: '2026-07-25T00:00:00',
  due_date: '2026-08-05T00:00:00',
  total_amount: '1000.00',
  computed_total: '1000.00',
  is_overdue: false,
  paid_amount: '300.00',
  remaining_amount: '700.00',
  payments: [{ id: 1, amount: '300.00', paid_at: '2026-07-28T12:00:00', account_id: null, note: null }],
  closed_at: '2026-07-25T00:00:00',
  paid_at: null,
  created_at: '2026-07-01T00:00:00',
  updated_at: '2026-07-28T00:00:00',
  transactions: [],
};

const FATURA_INTOCADA = {
  ...FATURA_PARCIAL,
  paid_amount: '0.00',
  remaining_amount: '1000.00',
  payments: [],
};

let detalhe: typeof FATURA_PARCIAL = FATURA_PARCIAL;

vi.mock('@/hooks/use-credit-cards', () => ({
  useCardStatements: () => ({
    statements: [{ ...FATURA_PARCIAL, is_current: true }],
    isLoading: false,
  }),
  useStatementDetail: () => ({ statement: detalhe, isLoading: false }),
  useStatementActions: () => ({ close: vi.fn(), pay, reopen: vi.fn(), isPending: false }),
}));
vi.mock('@/hooks/use-payment-accounts', () => ({
  usePaymentAccounts: () => ({ activeAccounts: [] }),
}));
vi.mock('@/hooks/use-base-currency', () => ({ useBaseCurrency: () => 'BRL' }));
vi.mock('@/stores', () => ({ useTxDetailStore: () => vi.fn() }));

describe('StatementView — saldo da fatura', () => {
  beforeEach(() => {
    pay.mockReset();
    pay.mockResolvedValue({});
    detalhe = FATURA_PARCIAL;
  });

  it('mostra quanto já foi pago e quanto falta', () => {
    render(<StatementView cardId={1} />);
    expect(screen.getByText('Pago até agora')).toBeInTheDocument();
    expect(screen.getByText('Saldo restante')).toBeInTheDocument();
    expect(screen.getAllByText(/700,00/).length).toBeGreaterThan(0);
  });

  it('o botão fala em saldo quando já houve pagamento parcial', () => {
    render(<StatementView cardId={1} />);
    expect(screen.getByRole('button', { name: /Pagar saldo restante/ })).toBeInTheDocument();
  });

  it('numa fatura intocada, o botão continua sendo "Pagar fatura"', () => {
    detalhe = FATURA_INTOCADA;
    render(<StatementView cardId={1} />);
    expect(screen.getByRole('button', { name: /Pagar fatura/ })).toBeInTheDocument();
    expect(screen.queryByText('Pago até agora')).not.toBeInTheDocument();
  });

  it('envia o VALOR, não só a conta — e pré-preenche com o saldo', async () => {
    render(<StatementView cardId={1} />);
    fireEvent.click(screen.getByRole('button', { name: /Pagar saldo restante/ }));

    const campo = await screen.findByLabelText('Valor pago');
    expect((campo as HTMLInputElement).value).toContain('700,00');

    fireEvent.click(screen.getByRole('button', { name: 'Confirmar pagamento' }));
    await waitFor(() => expect(pay).toHaveBeenCalled());
    // O defeito antigo: o diálogo mandava só `account_id`.
    expect(pay.mock.calls[0][0]).toMatchObject({ statementId: 10, amount: 700 });
  });

  it('permite pagar menos que o saldo', async () => {
    render(<StatementView cardId={1} />);
    fireEvent.click(screen.getByRole('button', { name: /Pagar saldo restante/ }));

    const campo = await screen.findByLabelText('Valor pago');
    fireEvent.change(campo, { target: { value: '20000' } }); // R$ 200,00
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar pagamento' }));

    await waitFor(() => expect(pay).toHaveBeenCalled());
    expect(pay.mock.calls[0][0].amount).toBe(200);
  });
});
