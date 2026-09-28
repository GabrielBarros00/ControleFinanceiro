import { beforeEach, describe, expect, it, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { fireEvent, render, screen, waitFor } from '@/test/utils';
import { server } from '@/test/setup';
import { AmortizationTable } from '../AmortizationTable';

/**
 * Desfazer o pagamento de uma parcela.
 *
 * O backend estorna (`/unpay`: a parcela volta a aberta e a despesa que o
 * pagamento lançou é excluída) e o agente de IA já o fazia. A tela só sabia
 * pagar: o clique errado em "Pagar" não tinha volta por aqui.
 */
const parcela = (n: number, paga: boolean) => ({
  id: n, installment_number: n, due_date: `2026-0${n}-10`, total_amount: '1000.00',
  principal_amount: '600.00', interest_amount: '400.00', remaining_balance: '9000.00',
  is_paid: paga, paid_at: paga ? `2026-0${n}-10T12:00:00` : null,
});

const CONTRATO = {
  id: 1, title: 'Carro', total_amount: '30000.00', currency: 'BRL', interest_rate: '0.01',
  installments_count: 3, method: 'PRICE', start_date: '2026-01-10', status: 'active', outstanding: '20000.00',
};

const estornar = vi.hoisted(() => vi.fn(async () => {}));
const perguntar = vi.hoisted(() => vi.fn(async () => true));

vi.mock('@/hooks/use-financing', () => ({
  useFinancing: () => ({
    financings: [CONTRATO],
    isLoading: false,
    create: vi.fn(),
    remove: vi.fn(),
    quitarAnteriores: vi.fn(),
    payInstallment: vi.fn(),
    unpayInstallment: estornar,
  }),
  useFinancingSchedule: () => ({
    schedule: [parcela(1, true), parcela(2, false), parcela(3, false)],
    settlement: null,
  }),
}));
vi.mock('@/components/ui/confirm', () => ({ useConfirm: () => perguntar }));

describe('Financiamentos — desfazer o pagamento de uma parcela', () => {
  beforeEach(() => {
    estornar.mockClear();
    perguntar.mockClear();
    server.use(
      http.get('http://localhost:8000/api/v1/me/overview', () => HttpResponse.json({ currency: 'BRL' })),
    );
  });

  it('a parcela paga oferece desfazer, pergunta antes, e estorna', async () => {
    render(<AmortizationTable />);
    fireEvent.click(screen.getAllByRole('button', { name: 'Desfazer o pagamento da parcela 1' })[0]);

    await waitFor(() => expect(estornar).toHaveBeenCalledWith({ financingId: 1, installmentNumber: 1 }));
    expect(perguntar).toHaveBeenCalledWith(expect.objectContaining({ destructive: true }));
    // Só a paga: as abertas não têm o que desfazer.
    expect(screen.queryAllByRole('button', { name: 'Desfazer o pagamento da parcela 2' })).toHaveLength(0);
  });

  it('cancelar a pergunta não estorna nada', async () => {
    perguntar.mockResolvedValueOnce(false);
    render(<AmortizationTable />);
    fireEvent.click(screen.getAllByRole('button', { name: 'Desfazer o pagamento da parcela 1' })[0]);
    await waitFor(() => expect(perguntar).toHaveBeenCalled());
    expect(estornar).not.toHaveBeenCalled();
  });
});
