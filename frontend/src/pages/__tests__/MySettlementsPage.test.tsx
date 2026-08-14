import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { MySettlementsPage } from '../MySettlementsPage';

/**
 * Seus acertos — a camada global (ADR 0027).
 *
 * O que estes testes travam é o que a tela NÃO pode fazer: somar casas de moedas
 * diferentes, esconder a casa sem cotação, e mostrar um "saldo líquido" que
 * compense dívida de uma casa com crédito de outra.
 */
const DEBTS = {
  currency: 'BRL',
  to_pay: '100.00',
  to_receive: '120.00',
  by_workspace: [
    {
      workspace_id: 1,
      workspace_name: 'Casa',
      base_currency: 'BRL',
      role: 'member',
      can_write: true,
      converted: true,
      to_pay: '100.00',
      to_receive: '0.00',
      net_debts: [
        {
          debtor_id: 1, creditor_id: 2, amount: '100.00',
          debtor_name: 'Eu', creditor_name: 'Ana',
        },
      ],
    },
    {
      workspace_id: 2,
      workspace_name: 'Viagem',
      base_currency: 'BRL',
      role: 'owner',
      can_write: true,
      converted: true,
      to_pay: '0.00',
      to_receive: '120.00',
      net_debts: [
        {
          debtor_id: 3, creditor_id: 1, amount: '120.00',
          debtor_name: 'Bruno', creditor_name: 'Eu',
        },
      ],
    },
  ],
  excluded_workspaces: [],
};

const COM_CASA_SEM_COTACAO = {
  ...DEBTS,
  by_workspace: [
    ...DEBTS.by_workspace,
    {
      workspace_id: 3,
      workspace_name: 'Exterior',
      base_currency: 'USD',
      role: 'member',
      can_write: true,
      converted: false,
      to_pay: '90.00',
      to_receive: '0.00',
      net_debts: [
        {
          debtor_id: 1, creditor_id: 3, amount: '90.00',
          debtor_name: 'Eu', creditor_name: 'Bruno',
        },
      ],
    },
  ],
  excluded_workspaces: [
    {
      workspace_id: 3, workspace_name: 'Exterior', base_currency: 'USD',
      to_pay: '90.00', to_receive: '0.00',
    },
  ],
};

const MONTHLY = {
  month: '2026-08',
  by_workspace: [
    {
      workspace_id: 1,
      workspace_name: 'Casa',
      role: 'member',
      can_write: true,
      month: '2026-08',
      base_currency: 'BRL',
      members: [{ user_id: 1, paid: '0.00', owed: '100.00', balance: '-100.00' }],
      net_debts: [{ debtor_id: 1, creditor_id: 2, amount: '100.00' }],
      expenses: [
        {
          id: 10, title: 'Mercado', total_amount: '200.00', status: 'confirmed',
          is_paid: false, transaction_date: '2026-08-10T12:00:00Z',
          installment_no: null, installments_of: null,
          payers: [{ user_id: 2, amount: '200.00' }],
          splits: [
            { user_id: 1, computed_amount: '100.00' },
            { user_id: 2, computed_amount: '100.00' },
          ],
        },
      ],
      settled_total: '0.00',
      settlements: [],
      totals: { total: '200.00', paid: '0.00', open: '200.00' },
      people: [
        { user_id: 1, user_name: 'Eu' },
        { user_id: 2, user_name: 'Ana' },
      ],
    },
  ],
};

const HISTORICO = [
  {
    id: 5, workspace_id: 1, workspace_name: 'Casa', currency: 'BRL',
    from_user_id: 1, to_user_id: 2, counterparty_id: 2, counterparty_name: 'Ana',
    direction: 'sent', amount: '40.00', note: 'Pix', billing_month: null,
    settled_at: '2026-08-05T12:00:00Z', created_by_user_id: 1,
  },
  {
    id: 6, workspace_id: 2, workspace_name: 'Viagem', currency: 'BRL',
    from_user_id: 3, to_user_id: 1, counterparty_id: 3, counterparty_name: 'Bruno',
    direction: 'received', amount: '25.00', note: null, billing_month: null,
    settled_at: '2026-08-03T12:00:00Z', created_by_user_id: 3,
  },
];

const mockDebts = vi.fn();
const mockMonthly = vi.fn();
const mockHistory = vi.fn();

vi.mock('@/hooks/use-my-settlements', () => ({
  useMyDebts: () => mockDebts(),
  useMyMonthlyDebts: (...args: unknown[]) => mockMonthly(...args),
  useMySettlementsHistory: () => mockHistory(),
}));
vi.mock('@/hooks/use-auth', () => ({
  useAuth: () => ({ user: { id: 1, name: 'Eu' } }),
}));
// O dialog fala com o backend do workspace; aqui só interessa que a tela o monte.
vi.mock('@/components/debts/SettlementDialog', () => ({
  SettlementDialog: () => null,
}));

function renderPage(
  debts: unknown = DEBTS,
  extra: { isError?: boolean; refetch?: () => void } = {},
) {
  mockDebts.mockReturnValue({
    debts,
    isLoading: false,
    isError: extra.isError ?? false,
    refetch: extra.refetch ?? vi.fn(),
  });
  mockMonthly.mockReturnValue({ monthly: MONTHLY, isLoading: false, isError: false, refetch: vi.fn() });
  mockHistory.mockReturnValue({
    settlements: HISTORICO, total: HISTORICO.length,
    isLoading: false, isError: false, refetch: vi.fn(),
  });
  return render(
    <MemoryRouter initialEntries={['/me/settlements?month=2026-08']}>
      <MySettlementsPage />
    </MemoryRouter>,
  );
}

describe('Seus acertos', () => {
  beforeEach(() => {
    mockDebts.mockReset();
    mockMonthly.mockReset();
    mockHistory.mockReset();
  });

  it('mostra a pagar e a receber lado a lado, sem "saldo líquido"', () => {
    renderPage();
    // "Você deve" também titula o card de cada casa — o do topo é o total.
    expect(screen.getAllByText('Você deve').length).toBeGreaterThan(0);
    expect(screen.getByText('Você tem a receber')).toBeInTheDocument();
    expect(screen.getAllByText('Somando todas as casas')).toHaveLength(2);
    // Compensar 120 a receber com 100 a pagar entre casas diferentes seria dizer
    // que a dívida com a Ana foi paga pelo que o Bruno deve (ADR 0020).
    expect(screen.queryByText('Saldo líquido')).not.toBeInTheDocument();
  });

  it('agrupa por casa e leva para a tela de cada uma', () => {
    renderPage();
    expect(screen.getAllByText('Casa').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Viagem').length).toBeGreaterThan(0);
    const links = screen.getAllByRole('link', { name: /Abrir a casa/ });
    expect(links[0]).toHaveAttribute('href', '/w/1/debts');
  });

  it('mostra a casa sem cotação na moeda dela e avisa que ficou fora do total', () => {
    renderPage(COM_CASA_SEM_COTACAO);
    const aviso = screen.getByRole('status');
    expect(within(aviso).getByText(/Exterior/)).toBeInTheDocument();
    // O valor aparece em USD, não convertido nem zerado
    expect(within(aviso).getByText(/US\$|USD/)).toBeInTheDocument();
    expect(screen.getByText(/fora do total acima/)).toBeInTheDocument();
  });

  it('o histórico diz de qual casa veio cada acerto e de que lado eu estou', () => {
    renderPage();
    expect(screen.getByText('Você pagou')).toBeInTheDocument();
    expect(screen.getByText('Você recebeu de')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Viagem' })).toHaveAttribute('href', '/w/2/debts');
  });

  it('falha de API não vira "você não deve nada" (ERR-001)', () => {
    const refetch = vi.fn();
    renderPage(undefined, { isError: true, refetch });
    expect(screen.getByText(/Não foi possível carregar seus acertos/)).toBeInTheDocument();
    expect(screen.queryByText('Você tem a receber')).not.toBeInTheDocument();
  });

  it('sem saldo em casa nenhuma, mostra o estado vazio em vez de cards zerados', () => {
    renderPage({ ...DEBTS, to_pay: '0.00', to_receive: '0.00', by_workspace: [] });
    expect(screen.getByText('Nenhum acerto pendente')).toBeInTheDocument();
  });

  /*
   * Regressão: a seção do mês vivia DENTRO do `if (grupos.length)`. Como
   * `/me/debts` só lista casa com saldo pendente, quitar o mês fazia o retrato
   * dele sumir da tela junto com as despesas e o "tudo acertado ✅" — que é
   * justamente a confirmação que a pessoa foi procurar depois de pagar.
   */
  it('o mês continua na tela mesmo com tudo quitado', () => {
    renderPage({ ...DEBTS, to_pay: '0.00', to_receive: '0.00', by_workspace: [] });
    expect(screen.getByText('Nenhum acerto pendente')).toBeInTheDocument();
    // Título da seção — o texto também aparece como rótulo dentro do ledger.
    expect(screen.getByRole('heading', { name: /Acertos do mês/ })).toBeInTheDocument();
    expect(screen.getByText('Mercado')).toBeInTheDocument();
  });

  it('avisa quando o histórico está truncado', () => {
    mockDebts.mockReturnValue({ debts: DEBTS, isLoading: false, isError: false, refetch: vi.fn() });
    mockMonthly.mockReturnValue({ monthly: MONTHLY, isLoading: false, isError: false, refetch: vi.fn() });
    mockHistory.mockReturnValue({
      settlements: HISTORICO, total: 120, isLoading: false, isError: false, refetch: vi.fn(),
    });
    render(
      <MemoryRouter initialEntries={['/me/settlements?month=2026-08']}>
        <MySettlementsPage />
      </MemoryRouter>,
    );
    expect(screen.getByText(/Mostrando os 2 mais recentes de 120/)).toBeInTheDocument();
  });

  it('pede o mês da URL ao hook do ledger mensal', () => {
    renderPage();
    expect(mockMonthly).toHaveBeenCalledWith('2026-08');
    expect(screen.getByText('Mercado')).toBeInTheDocument();
  });
});
