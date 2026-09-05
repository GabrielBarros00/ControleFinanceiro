import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { MySettlementsPage } from '../MySettlementsPage';

/**
 * Seus acertos — a camada global (ADR 0027), agora em três abas.
 *
 * O que estes testes travam é o que a tela NÃO pode fazer: somar casas de moedas
 * diferentes, esconder a casa sem cotação, mostrar um "saldo líquido" que
 * compense dívida de uma casa com crédito de outra — e, desde o redesenho,
 * exibir uma origem de saldo que não fecha a conta.
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

/** A origem do saldo da Casa: 60 de julho + 60 de agosto, menos 20 já acertados
 *  "por fora" — os 100 que aparecem no card. */
const ORIGEM = [
  {
    workspace_id: 1,
    workspace_name: 'Casa',
    base_currency: 'BRL',
    balance: '-100.00',
    months: [
      { month: '2026-08', balance: '-60.00', net_debts: [], settled: '0.00' },
      { month: '2026-07', balance: '-60.00', net_debts: [], settled: '15.00' },
    ],
    older: { count: 0, balance: '0.00' },
    unassigned: '20.00',
  },
  {
    workspace_id: 2,
    workspace_name: 'Viagem',
    base_currency: 'BRL',
    balance: '120.00',
    months: [{ month: '2026-08', balance: '120.00', net_debts: [], settled: '0.00' }],
    older: { count: 0, balance: '0.00' },
    unassigned: '0.00',
  },
];

const HISTORICO = [
  {
    id: 5, workspace_id: 1, workspace_name: 'Casa', currency: 'BRL',
    from_user_id: 1, to_user_id: 2, counterparty_id: 2, counterparty_name: 'Ana',
    direction: 'sent', amount: '40.00', note: 'Pix', billing_month: '2026-07',
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
const mockOrigem = vi.fn();

vi.mock('@/hooks/use-my-settlements', () => ({
  useMyDebts: () => mockDebts(),
  useMyMonthlyDebts: (...args: unknown[]) => mockMonthly(...args),
  useMySettlementsHistory: () => mockHistory(),
}));
vi.mock('@/hooks/use-debts-by-month', () => ({
  useMyDebtsByMonth: () => mockOrigem(),
}));
vi.mock('@/hooks/use-auth', () => ({
  useAuth: () => ({ user: { id: 1, name: 'Eu' } }),
}));
// O dialog fala com o backend do workspace; aqui só interessa que a tela o monte.
vi.mock('@/components/debts/SettlementDialog', () => ({
  SettlementDialog: () => null,
}));

/**
 * O Radix Tabs ativa a aba no `mousedown`, não no `click` sintético — e o
 * conteúdo inativo é desmontado. Sem o `mousedown`, procurar qualquer coisa de
 * outra aba falha com "elemento não encontrado", o que parece defeito da tela e
 * é só o disparo errado. Mesmo helper de `AdminPage.test.tsx`.
 */
function abrirAba(nome: string) {
  const gatilho = screen.getByRole('tab', { name: nome });
  fireEvent.mouseDown(gatilho);
  fireEvent.click(gatilho);
}

/**
 * `QueryClientProvider` não é enfeite: o `ScopeBadge` do cabeçalho lê
 * `useWorkspaces` para saber o nome do espaço, e sem o provider o hook lança e a
 * tela inteira falha ao montar. Ele é a pílula que distingue "Acertos" de "Seus
 * acertos" num scan visual — o par homônimo que o próprio componente cita.
 */
function montar(entrada = '/me/settlements?month=2026-08') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[entrada]}>
        <MySettlementsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

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
  mockOrigem.mockReturnValue({ grupos: ORIGEM, isLoading: false, isError: false, refetch: vi.fn() });
  mockHistory.mockReturnValue({
    settlements: HISTORICO, total: HISTORICO.length,
    isLoading: false, isError: false, refetch: vi.fn(),
  });
  return montar();
}

describe('Seus acertos', () => {
  beforeEach(() => {
    mockDebts.mockReset();
    mockMonthly.mockReset();
    mockHistory.mockReset();
    mockOrigem.mockReset();
  });

  it('abre no Resumo, com a pagar e a receber lado a lado e sem "saldo líquido"', () => {
    renderPage();
    expect(screen.getByRole('tab', { name: 'Resumo' })).toHaveAttribute('data-state', 'active');
    expect(screen.getByText('Você deve')).toBeInTheDocument();
    expect(screen.getByText('Você tem a receber')).toBeInTheDocument();
    expect(screen.getAllByText('Acumulado, todos os espaços')).toHaveLength(2);
    // Compensar 120 a receber com 100 a pagar entre casas diferentes seria dizer
    // que a dívida com a Ana foi paga pelo que o Bruno deve (ADR 0020).
    expect(screen.queryByText('Saldo líquido')).not.toBeInTheDocument();
  });

  it('agrupa por casa e leva para a tela de cada uma', () => {
    renderPage();
    expect(screen.getAllByText('Casa').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Viagem').length).toBeGreaterThan(0);
    const links = screen.getAllByRole('link', { name: /Abrir o espaço/ });
    expect(links[0]).toHaveAttribute('href', '/w/1/debts');
  });

  /*
   * O redesenho trocou os dois cards "Você deve"/"Você recebe" por uma linha
   * POR PESSOA. O rótulo repetido era metade da confusão relatada: o título do
   * card era igual ao do total logo acima, e dentro de um espaço um dos dois
   * cards está sempre vazio por construção do pareamento.
   */
  it('mostra uma linha por pessoa, com a direção escrita', () => {
    renderPage();
    expect(screen.getByText('Ana')).toBeInTheDocument();
    expect(screen.getByText('você deve')).toBeInTheDocument();
    expect(screen.getByText('Bruno')).toBeInTheDocument();
    expect(screen.getByText('você recebe')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Paguei/ })).toBeEnabled();
    expect(screen.getByRole('button', { name: /Recebi/ })).toBeEnabled();
  });

  it('mostra a casa sem cotação na moeda dela e avisa que ficou fora do total', () => {
    renderPage(COM_CASA_SEM_COTACAO);
    const aviso = screen.getByRole('status');
    expect(within(aviso).getByText(/Exterior/)).toBeInTheDocument();
    // O valor aparece em USD, não convertido nem zerado
    expect(within(aviso).getByText(/US\$|USD/)).toBeInTheDocument();
    expect(screen.getByText(/fora do total acima/)).toBeInTheDocument();
  });

  /*
   * A queixa que originou o redesenho: "Saldo geral a acertar" é cumulativo, e
   * lido sozinho passa por cobrança do mês corrente. A quebra abre a soma — e
   * ela TEM de fechar, senão a pessoa perde a confiança nos dois números.
   */
  it('diz de onde vem o saldo, e a soma fecha com o total', () => {
    renderPage();
    // Cada casa tem a origem DELA: procurar solto acharia os dois "ago/2026" e
    // os dois "Total acumulado". O recorte é a seção da casa.
    const casa = screen.getByRole('heading', { name: /^Casa/ }).closest('section')!;

    expect(within(casa).getByText('ago/2026')).toBeInTheDocument();
    expect(within(casa).getByText('jul/2026')).toBeInTheDocument();
    expect(within(casa).getAllByText('você deve R$ 60,00')).toHaveLength(2);
    // O acerto sem mês é uma LINHA, não um sumiço: é ele que explica por que o
    // total (100) não é a soma dos meses (120).
    expect(within(casa).getByText('Acertos sem mês')).toBeInTheDocument();
    expect(within(casa).getByText('você recebe R$ 20,00')).toBeInTheDocument();
    // A conta fecha na tela: −60 −60 +20 = −100
    expect(within(casa).getByText('Total acumulado')).toBeInTheDocument();
    expect(within(casa).getByText('você deve R$ 100,00')).toBeInTheDocument();
    // E o mês parcialmente acertado diz quanto já foi
    expect(within(casa).getByText('R$ 15,00 já acertados')).toBeInTheDocument();
  });

  it('o histórico diz de qual casa veio cada acerto, de que lado eu estou e que mês ele fecha', () => {
    renderPage();
    abrirAba('Histórico');
    expect(screen.getByText('Você pagou')).toBeInTheDocument();
    expect(screen.getByText('Você recebeu de')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Viagem' })).toHaveAttribute('href', '/w/2/debts');
    // A pílula é a novidade: `billing_month` sempre veio na resposta e nunca
    // aparecia na tela, então os dois tipos de acerto eram indistinguíveis.
    expect(screen.getByText('jul/2026')).toBeInTheDocument();
    expect(screen.getByText('sem mês')).toBeInTheDocument();
  });

  /*
   * Regressão da auditoria: `useMyDebtsByMonth` devolvia `isError` e a tela não
   * o lia. Com a consulta falhando, o bloco "de onde vem esse saldo"
   * simplesmente não era desenhado — e quem já o conhece lê a ausência como "não
   * vem de mês nenhum", que é uma afirmação sobre dados que ninguém recebeu.
   */
  it('falha na origem do saldo aparece, em vez de o bloco sumir (ERR-001)', () => {
    mockDebts.mockReturnValue({ debts: DEBTS, isLoading: false, isError: false, refetch: vi.fn() });
    mockMonthly.mockReturnValue({ monthly: MONTHLY, isLoading: false, isError: false, refetch: vi.fn() });
    mockHistory.mockReturnValue({
      settlements: HISTORICO, total: 2, isLoading: false, isError: false, refetch: vi.fn(),
    });
    const refetch = vi.fn();
    mockOrigem.mockReturnValue({ grupos: [], isLoading: false, isError: true, refetch });
    montar();

    expect(screen.getByText(/Não foi possível abrir a origem dos saldos/)).toBeInTheDocument();
    // Uma vez só, não uma por espaço: a origem de todas as casas vem de uma
    // consulta, e N avisos idênticos seriam ruído.
    expect(screen.getAllByText(/Não foi possível abrir a origem dos saldos/)).toHaveLength(1);
    // O resto da tela continua de pé — só a quebra falhou.
    expect(screen.getByText('Você tem a receber')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Tentar novamente' }));
    expect(refetch).toHaveBeenCalled();
  });

  it('falha no ledger do mês não vira "nenhuma despesa neste mês" (ERR-001)', () => {
    mockDebts.mockReturnValue({ debts: DEBTS, isLoading: false, isError: false, refetch: vi.fn() });
    mockOrigem.mockReturnValue({ grupos: ORIGEM, isLoading: false, isError: false, refetch: vi.fn() });
    mockHistory.mockReturnValue({
      settlements: HISTORICO, total: 2, isLoading: false, isError: false, refetch: vi.fn(),
    });
    mockMonthly.mockReturnValue({ monthly: undefined, isLoading: false, isError: true, refetch: vi.fn() });
    montar();
    abrirAba('Por mês');

    expect(screen.getByText(/Não foi possível carregar o mês/)).toBeInTheDocument();
    expect(screen.queryByText('Nenhuma despesa em nenhum espaço neste mês.')).not.toBeInTheDocument();
  });

  it('falha de API não vira "você não deve nada" (ERR-001)', () => {
    const refetch = vi.fn();
    renderPage(undefined, { isError: true, refetch });
    expect(screen.getByText(/Não foi possível carregar seus acertos/)).toBeInTheDocument();
    expect(screen.queryByText('Você tem a receber')).not.toBeInTheDocument();
    // Sem resposta não há abas: mostrar a casca sugeriria que há o que ver
    expect(screen.queryByRole('tab')).not.toBeInTheDocument();
  });

  it('sem saldo em casa nenhuma, mostra o estado vazio em vez de cards zerados', () => {
    renderPage({ ...DEBTS, to_pay: '0.00', to_receive: '0.00', by_workspace: [] });
    expect(screen.getByText('Nenhum acerto pendente')).toBeInTheDocument();
  });

  /*
   * Regressão: a seção do mês vivia DENTRO do `if (grupos.length)`. Como
   * `/me/debts` só lista casa com saldo pendente, quitar o mês fazia o retrato
   * dele sumir da tela junto com as despesas e o "tudo acertado ✅" — que é
   * justamente a confirmação que a pessoa foi procurar depois de pagar. Com as
   * abas a independência continua valendo: a aba Por mês desenha o ledger mesmo
   * com `by_workspace` vazio no saldo.
   */
  it('o mês continua na tela mesmo com tudo quitado', () => {
    renderPage({ ...DEBTS, to_pay: '0.00', to_receive: '0.00', by_workspace: [] });
    expect(screen.getByText('Nenhum acerto pendente')).toBeInTheDocument();
    abrirAba('Por mês');
    expect(screen.getByText('Mercado')).toBeInTheDocument();
  });

  it('avisa quando o histórico está truncado', () => {
    mockDebts.mockReturnValue({ debts: DEBTS, isLoading: false, isError: false, refetch: vi.fn() });
    mockMonthly.mockReturnValue({ monthly: MONTHLY, isLoading: false, isError: false, refetch: vi.fn() });
    mockOrigem.mockReturnValue({ grupos: ORIGEM, isLoading: false, isError: false, refetch: vi.fn() });
    mockHistory.mockReturnValue({
      settlements: HISTORICO, total: 120, isLoading: false, isError: false, refetch: vi.fn(),
    });
    montar();
    abrirAba('Histórico');
    expect(screen.getByText(/Mostrando os 2 mais recentes de 120/)).toBeInTheDocument();
  });

  /*
   * `/me/debts/monthly` varre TODAS as casas e carrega as despesas de cada uma —
   * é a consulta mais cara da tela. Ela vivia no corpo da página e disparava
   * mesmo para quem só abria o Resumo; agora mora dentro da aba, que o Radix só
   * monta quando aberta. O mês pedido continua sendo o da URL.
   */
  it('só busca o ledger mensal quando a aba do mês é aberta, e com o mês da URL', () => {
    renderPage();
    expect(mockMonthly).not.toHaveBeenCalled();

    abrirAba('Por mês');
    expect(mockMonthly).toHaveBeenCalledWith('2026-08');
    expect(screen.getByText('Mercado')).toBeInTheDocument();
  });

  /*
   * A lista de despesas dominava a rolagem — uma vez POR CASA, nesta tela. Agora
   * fica atrás de um resumo com o número à vista. O `<details>` mantém o
   * conteúdo no DOM (jsdom não tem layout), então o que se testa é o resumo.
   */
  it('as despesas do mês vêm recolhidas, com o resumo na dobra', () => {
    renderPage();
    abrirAba('Por mês');
    const bloco = screen.getByText('Despesas do mês').closest('details');
    expect(bloco).not.toBeNull();
    expect(bloco).not.toHaveAttribute('open');
    expect(screen.getByText(/1 · R\$ 200,00 · 1 em aberto/)).toBeInTheDocument();
  });

  /*
   * A queixa: num mês de despesas rateadas, a primeira coisa da aba era "TOTAL
   * DO MÊS / PAGO / EM ABERTO" — o valor CHEIO dos lançamentos —, e só depois
   * "fulano deve R$ X a você". Aqui a coisa é pior que na tela da casa, porque
   * se repete uma vez por espaço.
   */
  it('cada espaço abre pela sua parte, não pelo total dos lançamentos', () => {
    renderPage();
    abrirAba('Por mês');
    expect(screen.getAllByText('Sua parte').length).toBeGreaterThan(0);
    expect(screen.getByText('Você pagou')).toBeInTheDocument();
    // Devo 100 dos 200 do Mercado — é esse o número, não os 200.
    expect(screen.getByText('Você deve')).toBeInTheDocument();
    expect(screen.queryByText('Total do mês')).not.toBeInTheDocument();
    expect(screen.getByText(/somam R\$ 200,00 no espaço/)).toBeInTheDocument();
  });

  it('a aba escolhida vai para a URL, para o link poder ser compartilhado', () => {
    renderPage();
    abrirAba('Histórico');
    expect(screen.getByRole('tab', { name: 'Histórico' })).toHaveAttribute('data-state', 'active');
    abrirAba('Resumo');
    expect(screen.getByRole('tab', { name: 'Resumo' })).toHaveAttribute('data-state', 'active');
  });

  it('link direto para uma aba abre nela', () => {
    mockDebts.mockReturnValue({ debts: DEBTS, isLoading: false, isError: false, refetch: vi.fn() });
    mockMonthly.mockReturnValue({ monthly: MONTHLY, isLoading: false, isError: false, refetch: vi.fn() });
    mockOrigem.mockReturnValue({ grupos: ORIGEM, isLoading: false, isError: false, refetch: vi.fn() });
    mockHistory.mockReturnValue({
      settlements: HISTORICO, total: 2, isLoading: false, isError: false, refetch: vi.fn(),
    });
    montar('/me/settlements?tab=mes&month=2026-08');
    expect(screen.getByRole('tab', { name: 'Por mês' })).toHaveAttribute('data-state', 'active');
    expect(screen.getByText('Mercado')).toBeInTheDocument();
  });
});
