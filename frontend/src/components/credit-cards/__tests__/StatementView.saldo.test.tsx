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
  // Anotado porque `typeof FATURA_PARCIAL` é o tipo de `detalhe`, e este arquivo
  // testa justamente a fatura JÁ paga: sem isto o TS infere o literal `null` e
  // recusa a data no fixture de baixo.
  paid_at: null as string | null,
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

const reopen = vi.fn();
const confirmar = vi.fn();

vi.mock('@/hooks/use-credit-cards', () => ({
  useCardStatements: () => ({
    statements: [{ ...FATURA_PARCIAL, is_current: true }],
    isLoading: false,
  }),
  // A fatura é denominada na moeda DO CARTÃO, não na do workspace aberto.
  useCreditCards: () => ({ cards: [{ id: 1, name: 'Nubank', currency: 'BRL' }] }),
  useStatementDetail: () => ({ statement: detalhe, isLoading: false }),
  useStatementActions: () => ({ close: vi.fn(), pay, reopen, isPending: false }),
}));
vi.mock('@/hooks/use-payment-accounts', () => ({
  usePaymentAccounts: () => ({ activeAccounts: [] }),
}));
vi.mock('@/components/ui/confirm', () => ({ useConfirm: () => confirmar }));
vi.mock('@/stores', () => ({ useTxDetailStore: () => vi.fn() }));

describe('StatementView — saldo da fatura', () => {
  beforeEach(() => {
    pay.mockReset();
    pay.mockResolvedValue({});
    reopen.mockReset();
    reopen.mockResolvedValue({});
    confirmar.mockReset();
    confirmar.mockResolvedValue(true);
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

/**
 * Reabrir ESTORNA os pagamentos.
 *
 * Com saldo cumulativo, uma fatura ainda "fechada" pode ter pagamentos parciais.
 * O botão dela dizia só "Reabrir" e agia na hora: um clique tirava dinheiro do
 * caixa e mexia no limite sem avisar — enquanto o botão da fatura PAGA já dizia
 * "estornar pagamento".
 */
describe('StatementView — reabrir com pagamento parcial', () => {
  beforeEach(() => {
    reopen.mockReset();
    reopen.mockResolvedValue({});
    confirmar.mockReset();
    confirmar.mockResolvedValue(true);
    detalhe = FATURA_PARCIAL;
  });

  it('o rótulo anuncia o estorno quando há o que estornar', () => {
    render(<StatementView cardId={1} />);
    expect(
      screen.getByRole('button', { name: /Reabrir \(estornar pagamentos\)/ }),
    ).toBeInTheDocument();
  });

  it('pede confirmação dizendo quanto será estornado', async () => {
    render(<StatementView cardId={1} />);
    fireEvent.click(screen.getByRole('button', { name: /Reabrir/ }));

    await waitFor(() => expect(confirmar).toHaveBeenCalled());
    expect(confirmar.mock.calls[0][0].description).toContain('300,00');
    await waitFor(() => expect(reopen).toHaveBeenCalledWith(10));
  });

  it('cancelar NÃO estorna', async () => {
    confirmar.mockResolvedValue(false);
    render(<StatementView cardId={1} />);
    fireEvent.click(screen.getByRole('button', { name: /Reabrir/ }));

    await waitFor(() => expect(confirmar).toHaveBeenCalled());
    expect(reopen).not.toHaveBeenCalled();
  });

  it('sem pagamento nenhum, reabre direto — confirmação seria ruído', async () => {
    detalhe = FATURA_INTOCADA;
    render(<StatementView cardId={1} />);
    fireEvent.click(screen.getByRole('button', { name: /Reabrir/ }));

    await waitFor(() => expect(reopen).toHaveBeenCalledWith(10));
    expect(confirmar).not.toHaveBeenCalled();
  });
});

/**
 * Fatura `paid` com saldo devedor — o estado contraditório.
 *
 * O backfill da perna de fatura podia recalcular o total de uma fatura já paga e
 * descobrir que ela fora paga a menos. Enquanto o bloco de saldo dependia do
 * STATUS (`status !== 'paid'`), a tela mostrava só "Total da Fatura" e o selo
 * "Paga": a diferença não aparecia em lugar nenhum. O critério passou a ser o
 * saldo. O script agora devolve essas faturas para `closed`, mas quem já rodou a
 * versão anterior tem o estado no banco — e a tela não pode escondê-lo.
 */
describe('StatementView — fatura paga com saldo devedor', () => {
  const FATURA_PAGA_SUBPAGA = {
    ...FATURA_PARCIAL,
    status: 'paid',
    total_amount: '20.70',
    computed_total: '20.70',
    paid_amount: '5.00',
    remaining_amount: '15.70',
    paid_at: '2026-07-28T12:00:00',
    payments: [{ id: 1, amount: '5.00', paid_at: '2026-07-28T12:00:00', account_id: null, note: null }],
  };

  beforeEach(() => {
    detalhe = FATURA_PAGA_SUBPAGA;
  });

  it('mostra o saldo que ainda falta, apesar do status "paga"', () => {
    render(<StatementView cardId={1} />);
    expect(screen.getByText('Saldo restante')).toBeInTheDocument();
    expect(screen.getAllByText(/15,70/).length).toBeGreaterThan(0);
    expect(screen.getByText('Pago até agora')).toBeInTheDocument();
  });

  it('uma fatura paga DE VERDADE não ganha o bloco de saldo', () => {
    detalhe = {
      ...FATURA_PAGA_SUBPAGA,
      paid_amount: '20.70',
      remaining_amount: '0.00',
    };
    render(<StatementView cardId={1} />);
    expect(screen.queryByText('Saldo restante')).not.toBeInTheDocument();
  });
});
