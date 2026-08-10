import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { StatementView } from '../StatementView';

/**
 * A linha da fatura mostra o valor DE FATURA (ADR 0024).
 *
 * O defeito que uma auditoria reproduziu no navegador: cartão em USD, workspace
 * em BRL, despesa de R$ 100. A célula desenhava `total_amount` — a perna
 * CONTÁBIL, gravada na moeda-base do workspace — e a rotulava com a moeda do
 * cartão. Saía `−US$ 100,00` numa fatura cujo total dizia `US$ 0,00`: o número
 * certo com o símbolo errado, ao lado de um total que não o continha.
 *
 * Agora a célula lê `statement_amount`/`statement_currency`, que é a mesma
 * população que o backend soma.
 */
const FATURA_MULTIMOEDA = {
  id: 10,
  card_id: 1,
  month: '2026-08',
  status: 'open',
  closing_date: '2026-08-20T00:00:00',
  due_date: '2026-08-28T00:00:00',
  total_amount: '0.00',
  computed_total: '20.70',
  is_overdue: false,
  paid_amount: '0.00',
  remaining_amount: '20.70',
  payments: [],
  excluded_from_total_count: 0,
  closed_at: null,
  paid_at: null,
  created_at: '2026-08-01T00:00:00',
  updated_at: '2026-08-10T00:00:00',
  transactions: [
    {
      id: 1,
      title: 'Mercado',
      transaction_date: '2026-08-10T15:00:00',
      // A perna contábil: o que a compra pesa no orçamento do workspace.
      total_amount: '100.00',
      currency: 'BRL',
      // A perna de fatura: o que o banco cobra.
      statement_amount: '20.70',
      statement_currency: 'USD',
      status: 'confirmed',
      workspace_id: 1,
      installment_no: null,
      installments_of: null,
      original_amount: null,
      original_currency: null,
      exchange_rate: null,
      iof_rate: null,
      rate_source: null,
    },
  ],
};

const reopen = vi.fn();
const confirmar = vi.fn();
let detalhe: typeof FATURA_MULTIMOEDA = FATURA_MULTIMOEDA;

vi.mock('@/hooks/use-credit-cards', () => ({
  useCardStatements: () => ({
    statements: [{ ...FATURA_MULTIMOEDA, is_current: true }],
    isLoading: false,
  }),
  useCreditCards: () => ({ cards: [{ id: 1, name: 'Gringo', currency: 'USD' }] }),
  useStatementDetail: () => ({ statement: detalhe, isLoading: false }),
  useStatementActions: () => ({ close: vi.fn(), pay: vi.fn(), reopen, isPending: false }),
}));
vi.mock('@/hooks/use-payment-accounts', () => ({
  usePaymentAccounts: () => ({ activeAccounts: [] }),
}));
vi.mock('@/components/ui/confirm', () => ({ useConfirm: () => confirmar }));
vi.mock('@/stores', () => ({ useTxDetailStore: () => vi.fn() }));

describe('StatementView — cartão em moeda diferente do workspace', () => {
  beforeEach(() => {
    reopen.mockReset();
    reopen.mockResolvedValue({});
    confirmar.mockReset();
    confirmar.mockResolvedValue(true);
    detalhe = FATURA_MULTIMOEDA;
  });

  it('a linha mostra o valor de fatura, não o contábil', () => {
    render(<StatementView cardId={1} />);
    // US$ 20,70 (o que a fatura cobra) e não 100,00 rotulado como dólar.
    expect(screen.getAllByText(/20,70/).length).toBeGreaterThan(0);
  });

  it('mostra também o valor contábil, para a conversão não parecer erro', () => {
    render(<StatementView cardId={1} />);
    expect(screen.getByText(/no workspace/)).toBeInTheDocument();
    expect(screen.getByText(/100,00/)).toBeInTheDocument();
  });

  it('a soma das linhas é o total exibido', () => {
    render(<StatementView cardId={1} />);
    // `computed_total` = 20,70 = a única linha. O sintoma antigo era um total de
    // zero com a compra logo acima dele.
    const total = screen.getAllByText(/20,70/);
    expect(total.length).toBeGreaterThanOrEqual(2); // a linha e o total
  });
});

describe('StatementView — reabrir fatura', () => {
  beforeEach(() => {
    reopen.mockReset();
    reopen.mockResolvedValue({});
    confirmar.mockReset();
    confirmar.mockResolvedValue(true);
    detalhe = {
      ...FATURA_MULTIMOEDA,
      status: 'paid',
      paid_amount: '20.70',
      remaining_amount: '0.00',
      payments: [
        { id: 1, amount: '20.70', paid_at: '2026-08-28T12:00:00', account_id: null, note: null },
      ],
    } as unknown as typeof FATURA_MULTIMOEDA;
  });

  it('a confirmação diz que o dinheiro VOLTA para o caixa', async () => {
    // O texto estava invertido: dizia que o pagamento "volta a sair do seu
    // caixa". `reopen` faz soft delete dos pagamentos, e pagamento de fatura é a
    // saída de caixa (ADR 0022) — estorná-lo devolve o dinheiro ao mês.
    render(<StatementView cardId={1} />);
    fireEvent.click(screen.getByRole('button', { name: /Reabrir/i }));

    await waitFor(() => expect(confirmar).toHaveBeenCalled());
    const { description } = confirmar.mock.calls[0][0];
    expect(description).toMatch(/volta para o seu caixa/i);
    expect(description).not.toMatch(/volta a sair/i);
    expect(description).toMatch(/limite do cartão volta a ficar comprometido/i);
  });
});
