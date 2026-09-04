import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@/test/utils';
import { AmortizationTable } from '../AmortizationTable';

/**
 * "Próxima parcela" com data no passado.
 *
 * A captura do catálogo mostrou o quadro anunciando **"Vence em 31/08/2025"**
 * num dia de setembro de 2026 — um ano de atraso apresentado como a próxima
 * coisa a acontecer. A causa é a mesma que a tela de Compromissos já corrigiu:
 * `unpaid[0]` é a parcela mais antiga EM ABERTO, e num contrato cadastrado
 * depois de já ter começado ela está no passado.
 *
 * O defeito morava em dois lugares porque cada tela derivava a "próxima" por
 * conta própria. Este teste tranca o segundo.
 *
 * As duas perguntas são distintas e a tela responde as duas:
 * - *quando vence a próxima?* → a primeira com vencimento a partir de hoje;
 * - *qual eu pago primeiro?* → a mais antiga em aberto, vencida ou não.
 */
const HOJE = new Date();
const dia = (offset: number) => {
  const d = new Date(HOJE);
  d.setDate(d.getDate() + offset);
  return d.toISOString().slice(0, 10);
};

const parcela = (n: number, offsetDias: number, paga = false) => ({
  id: n,
  installment_number: n,
  due_date: dia(offsetDias),
  total_amount: '1000.00',
  principal_amount: '600.00',
  interest_amount: '400.00',
  remaining_balance: `${100000 - n * 600}.00`,
  is_paid: paga,
  paid_at: null,
});

const CONTRATO = {
  id: 1, title: 'Apartamento', total_amount: '300000.00', currency: 'BRL',
  interest_rate: '0.008', installments_count: 4, method: 'PRICE',
  start_date: dia(-400), status: 'active', outstanding: '250000.00',
};

vi.mock('@/hooks/use-financing', () => ({
  useFinancing: () => ({
    financings: [CONTRATO],
    isLoading: false,
    create: vi.fn(),
    remove: vi.fn(),
    quitarAnteriores: vi.fn(),
  }),
  useFinancingSchedule: () => ({
    // Três vencidas e uma a vencer: o caso de quem cadastra um contrato antigo.
    schedule: [parcela(1, -60), parcela(2, -30), parcela(3, -5), parcela(4, +25)],
    settlement: null,
    payInstallment: vi.fn(),
  }),
}));
vi.mock('@/components/ui/confirm', () => ({ useConfirm: () => vi.fn() }));

describe('Financiamentos — quadro "Próxima parcela"', () => {
  it('não anuncia como próxima uma parcela que já venceu', () => {
    render(<AmortizationTable />);

    const daquiA25 = new Date(HOJE);
    daquiA25.setDate(daquiA25.getDate() + 25);
    expect(
      screen.getByText(`Vence em ${daquiA25.toLocaleDateString('pt-BR')}`),
      'a "próxima" tem de ser a primeira a partir de hoje, não a mais antiga em aberto',
    ).toBeInTheDocument();
  });

  it('mostra o atraso em vez de escondê-lo junto com a correção', () => {
    render(<AmortizationTable />);
    // Contrapeso: sozinho, o teste acima passaria por uma correção que
    // simplesmente ignora o que venceu.
    expect(screen.getByText(/3 parcela\(s\) vencida\(s\)/)).toBeInTheDocument();
  });

  it('mantém o "Pagar" na parcela mais antiga em aberto', () => {
    render(<AmortizationTable />);
    // Qual VENCE e qual se PAGA primeiro são perguntas diferentes: a segunda é
    // sempre a mais antiga em aberto, senão a pessoa pula a fila da dívida.
    expect(screen.getAllByRole('button', { name: /^pagar$/i })).toHaveLength(1);
  });
});
