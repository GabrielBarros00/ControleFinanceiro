import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { OverviewPage } from '../OverviewPage';

/**
 * A primeira tela depois da Onda 2 — "Hoje".
 *
 * ## O que este arquivo substitui
 *
 * Ele nasceu de `OverviewPage.caixa.test.tsx`, que protegia a distinção
 * competência × caixa (ADR 0022) **nesta tela**. Os números de caixa saíram
 * daqui: entrou/saiu/saldo do mês eram uma cópia literal do topo do Extrato, e
 * renda/consumo/adiantado/resultado viraram série histórica em Seus relatórios.
 *
 * As invariantes que aquele arquivo trancava não foram abandonadas — elas
 * seguiram os números:
 *
 * - "consumo e caixa são valores distintos" e "resultado é renda − consumo, não
 *   renda − caixa" → `backend/tests/api/test_visao_global.py`
 *   (`test_consumo_e_caixa_sao_numeros_diferentes`, `test_resultado_usa_consumo_e_nao_caixa`);
 * - "entrou / saiu / saldo do mês aparecem com o detalhamento" →
 *   `GlobalLedgerPage.test.tsx`;
 * - "o nome acessível do link de drill-down cita rótulo E valor" → idem, onde o
 *   drill-down agora vive.
 *
 * O que ficou aqui é o que só esta tela responde: **quanto tenho**, **o que
 * precisa de mim** e **como está o mês**, nessa ordem e sem rolagem.
 */
const OVERVIEW = {
  month: '2026-07',
  currency: 'BRL',
  income: '9000.00',
  consumption: '400.00',
  paid_in_transactions: '300.00',
  result: '8600.00',
  cash_in: '9000.00',
  cash_out: '1000.00',
  net_cash: '8000.00',
  cash_out_breakdown: {
    transactions: '300.00', statement_payments: '700.00',
    settlements_sent: '0.00', financing_installments: '0.00',
  },
  cash_in_breakdown: { income: '9000.00', settlements_received: '0.00' },
  to_pay: '0.00',
  to_receive: '100.00',
  by_workspace: [],
  excluded_foreign_count: 0,
};

const SALDO = {
  currency: 'BRL',
  total: '8430.20',
  accounts: [
    {
      account_id: 1, name: 'Nubank', type: 'checking', currency: 'BRL',
      active: true, is_default: true,
      opening_amount: '8000.00', opening_on: '2026-07-01',
      balance: '5930.20', movements_counted: 3,
    },
  ],
  month: '2026-07',
  receivable_total: '6000.00',
  payable_total: '4380.00',
  overdue_total: '0.00',
  projected_balance: '10050.20',
  breakdown: [
    { kind: 'income', label: 'Rendas a receber', amount: '6000.00', count: 1 },
    { kind: 'payables', label: 'Contas a pagar', amount: '2880.00', count: 4 },
  ],
  unassigned_movements: 0,
  movements_before_opening: 0,
  accounts_without_opening: 0,
  excluded_foreign_count: 0,
};

const ATIVIDADE = [
  {
    id: 7, workspace_id: 1, workspace_name: 'Casa', title: 'Jantar',
    total_amount: '200.00', my_share: '100.00', currency: 'BRL',
    transaction_date: '2026-07-10T12:00:00Z', status: 'confirmed',
  },
];

const mockOverview = vi.hoisted(() => vi.fn());
const mockBalance = vi.hoisted(() => vi.fn());

vi.mock('@/hooks/use-overview', () => ({
  useOverview: (...args: unknown[]) => mockOverview(...args),
  useMyActivity: () => ({ activity: ATIVIDADE, isLoading: false }),
}));
vi.mock('@/hooks/use-balance', () => ({
  useBalance: (...args: unknown[]) => mockBalance(...args),
}));
vi.mock('@/hooks/use-auth', () => ({
  useAuth: () => ({ user: { id: 1, name: 'Gabriel Barros' } }),
}));
vi.mock('@/hooks/use-payables', () => ({
  useMyPayables: () => ({
    payables: { currency: 'BRL', month: '2026-07', entries: [], upcoming: [] },
    isLoading: false,
  }),
  useSettlePayables: () => ({ settle: vi.fn(), isSettling: false }),
}));

const desenhar = () => render(
  <MemoryRouter>
    <OverviewPage />
  </MemoryRouter>,
);

beforeEach(() => {
  mockOverview.mockReturnValue({
    overview: OVERVIEW, isLoading: false, isError: false, refetch: vi.fn(),
  });
  mockBalance.mockReturnValue({
    balance: SALDO, isLoading: false, isError: false, refetch: vi.fn(),
  });
});

describe('Hoje — o saldo é a primeira resposta', () => {
  it('mostra quanto a pessoa tem, uma vez só', () => {
    desenhar();
    // Uma vez, e não três: o saldo aparecia no total, num tile "Saldo atual" e
    // dentro do "Saldo projetado", na mesma tela e a poucos pixels de distância.
    expect(screen.getAllByText('R$ 8.430,20')).toHaveLength(1);
  });

  it('traduz a projeção em consequência, não em mais um número solto', () => {
    desenhar();
    expect(screen.getByText(/Pagando o que vence até o fim do mês/i)).toBeInTheDocument();
    expect(screen.getByText('R$ 10.050,20')).toBeInTheDocument();
  });

  it('conta sem saldo configurado PEDE o número em vez de mostrar zero', () => {
    // "Você não tem dinheiro" e "eu não sei quanto você tem" são respostas
    // diferentes, e só uma delas é verdade.
    mockBalance.mockReturnValue({
      balance: { ...SALDO, total: null, projected_balance: null },
      isLoading: false, isError: false, refetch: vi.fn(),
    });
    desenhar();

    expect(screen.getByText('Saldo ainda não configurado')).toBeInTheDocument();
    expect(screen.queryByText('R$ 0,00')).not.toBeInTheDocument();
  });
});

describe('Hoje — o mês em uma linha', () => {
  it('diz quanto foi consumido de quanto entrou', () => {
    desenhar();
    const secao = screen.getByRole('heading', { name: 'Este mês' }).closest('section')!;
    expect(within(secao).getByText('R$ 400,00')).toBeInTheDocument();
    expect(within(secao).getByText('R$ 9.000,00')).toBeInTheDocument();
  });

  it('avisa quando o consumo passou da renda', () => {
    mockOverview.mockReturnValue({
      overview: { ...OVERVIEW, income: '1000.00', consumption: '1500.00' },
      isLoading: false, isError: false, refetch: vi.fn(),
    });
    desenhar();
    // O caso que interessa: a barra satura e a frase muda de "sobraram" para
    // "a mais do que entrou".
    expect(screen.getByText(/R\$\s*500,00 a mais do que entrou/)).toBeInTheDocument();
  });
});

describe('Hoje — últimos lançamentos', () => {
  it('mostra a MINHA parte em destaque, com o total como referência', () => {
    desenhar();
    const secao = screen.getByRole('heading', { name: 'Últimos lançamentos' }).closest('section')!;
    // A lista mostrava `total_amount`: num rateio 50/50, o jantar de 200
    // aparecia como 200 para quem consumiu 100.
    expect(within(secao).getByText(/R\$\s*100,00/)).toBeInTheDocument();
    expect(within(secao).getByText(/de\s*R\$\s*200,00/)).toBeInTheDocument();
  });
});

describe('Hoje — erro nunca vira um mês de zeros (ERR-001)', () => {
  it('falha da API mostra erro com retry, não "Consumo R$ 0,00"', () => {
    const refetch = vi.fn();
    mockOverview.mockReturnValue({
      overview: undefined, isLoading: false, isError: true, refetch,
    });
    desenhar();

    expect(screen.getByText(/Não foi possível carregar a sua visão do mês/i)).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Este mês' })).not.toBeInTheDocument();
  });
});
