import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { ConfirmProvider } from '@/components/ui/confirm';
import { DebtsPage } from '../DebtsPage';

/**
 * Acertos de UMA casa — a tela que não tinha teste nenhum até o redesenho.
 *
 * O que estes casos travam é a leitura que a tela precisa produzir, e que ela
 * não produzia: qual número é do MÊS e qual é do ACUMULADO, de onde o acumulado
 * vem, e que existem dois tipos de acerto (o que fecha um mês e o que só abate o
 * total).
 */
const DEBTS = [
  { debtor_id: 1, creditor_id: 2, amount: '320.00' },
  // Dívida entre terceiros: só quem tem acesso completo recebe esta linha, e ela
  // não pode se misturar com as minhas.
  { debtor_id: 3, creditor_id: 2, amount: '45.00' },
];

const ORIGEM = {
  base_currency: 'BRL',
  balance: '-320.00',
  months: [
    { month: '2026-08', balance: '-200.00', net_debts: [], settled: '0.00' },
    { month: '2026-07', balance: '-120.00', net_debts: [], settled: '40.00' },
  ],
  older: { count: 0, balance: '0.00' },
  unassigned: '0.00',
};

const LEDGER = {
  month: '2026-08',
  base_currency: 'BRL',
  members: [{ user_id: 1, paid: '0.00', owed: '200.00', balance: '-200.00' }],
  net_debts: [{ debtor_id: 1, creditor_id: 2, amount: '200.00' }],
  expenses: [
    {
      id: 10, title: 'Mercado', total_amount: '400.00', status: 'confirmed',
      is_paid: false, transaction_date: '2026-08-10T12:00:00Z',
      installment_no: null, installments_of: null,
      payers: [{ user_id: 2, amount: '400.00' }],
      splits: [
        { user_id: 1, computed_amount: '200.00' },
        { user_id: 2, computed_amount: '200.00' },
      ],
    },
  ],
  settled_total: '40.00',
  settlements: [],
  totals: { total: '400.00', paid: '0.00', open: '400.00' },
};

const SETTLEMENTS = [
  {
    id: 7, from_user_id: 1, to_user_id: 2, amount: '40.00', note: 'Pix',
    billing_month: '2026-07', settled_at: '2026-08-01T12:00:00Z', created_by_user_id: 1,
  },
  {
    id: 8, from_user_id: 1, to_user_id: 2, amount: '15.00', note: null,
    billing_month: null, settled_at: '2026-07-20T12:00:00Z', created_by_user_id: 1,
  },
];

const MEMBERS = [
  { user_id: 1, user_name: 'Eu' },
  { user_id: 2, user_name: 'Ana' },
  { user_id: 3, user_name: 'Bruno' },
];

const mockDebts = vi.fn();
const mockOrigem = vi.fn();
const mockLedger = vi.fn();
const mockSettlements = vi.fn();
const mockRole = vi.fn();

vi.mock('@/hooks/use-debts', () => ({ useDebts: () => mockDebts() }));
vi.mock('@/hooks/use-debts-by-month', () => ({ useDebtsByMonth: () => mockOrigem() }));
vi.mock('@/hooks/use-monthly-debts', () => ({ useMonthlyDebts: () => mockLedger() }));
vi.mock('@/hooks/use-settlements', () => ({ useSettlements: () => mockSettlements() }));
vi.mock('@/hooks/use-members', () => ({ useMembers: () => ({ members: MEMBERS }) }));
vi.mock('@/hooks/use-base-currency', () => ({ useBaseCurrency: () => 'BRL' }));
vi.mock('@/hooks/use-workspace-role', () => ({ useWorkspaceRole: () => mockRole() }));
vi.mock('@/hooks/use-auth', () => ({ useAuth: () => ({ user: { id: 1, name: 'Eu' } }) }));
vi.mock('@/components/debts/SettlementDialog', () => ({ SettlementDialog: () => null }));

/** Radix ativa a aba no `mousedown`; ver `AdminPage.test.tsx`. */
function abrirAba(nome: string) {
  const gatilho = screen.getByRole('tab', { name: nome });
  fireEvent.mouseDown(gatilho);
  fireEvent.click(gatilho);
}

function montar(entrada = '/w/1/debts?month=2026-08') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[entrada]}>
        {/* `useConfirm` é o caminho do desfazer — o projeto proíbe
            `window.confirm`, então sem o provider o hook lança. */}
        <ConfirmProvider>
          <DebtsPage />
        </ConfirmProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Acertos do espaço', () => {
  beforeEach(() => {
    mockDebts.mockReturnValue({ debts: DEBTS, isLoading: false, isError: false, refetch: vi.fn() });
    mockOrigem.mockReturnValue({ origem: ORIGEM, isLoading: false, isError: false, refetch: vi.fn() });
    mockLedger.mockReturnValue({ ledger: LEDGER, isLoading: false, isError: false, refetch: vi.fn() });
    mockSettlements.mockReturnValue({
      settlements: SETTLEMENTS, isLoading: false, create: vi.fn(), remove: vi.fn(), isMutating: false,
    });
    mockRole.mockReturnValue({ canWrite: true });
  });

  /*
   * O topo tinha três `StatTile` — "Você deve", "Você recebe", "Saldo líquido" —
   * e dois deles eram sempre zero: `_settle_balances` põe cada pessoa em UM lado
   * só. Agora é uma frase e um número, com o escopo escrito.
   */
  it('o topo diz um número só, e diz que ele é acumulado', () => {
    montar();
    // O valor aparece duas vezes de propósito (aqui e na linha da Ana): o
    // recorte é o bloco do topo.
    const topo = screen.getByText('Você deve, no total').closest('div')!;
    expect(within(topo).getByText('R$ 320,00')).toBeInTheDocument();
    expect(
      within(topo).getByText(/Acumulado de todos os meses deste espaço — não é o do mês atual/),
    ).toBeInTheDocument();
    expect(screen.queryByText('Saldo líquido')).not.toBeInTheDocument();
    expect(screen.queryByText('Você recebe')).not.toBeInTheDocument();
  });

  it('lista uma linha por pessoa, com a direção escrita e o botão certo', () => {
    montar();
    // Nome, direção e botão na MESMA linha — é esse pareamento que a versão de
    // dois cards não conseguia expressar sem repetir os rótulos do topo.
    const linha = screen.getByText('você deve').closest('li')!;
    expect(within(linha).getByText('Ana')).toBeInTheDocument();
    expect(within(linha).getByText('R$ 320,00')).toBeInTheDocument();
    expect(within(linha).getByRole('button', { name: /Paguei/ })).toBeInTheDocument();
    // A dívida entre terceiros NÃO entra na minha lista — ela tem bloco próprio.
    expect(screen.getByText(/Entre outras pessoas/)).toBeInTheDocument();
  });

  /*
   * A queixa que originou o redesenho: o acumulado lido sozinho vira cobrança do
   * mês. Agora a soma aparece aberta e fecha.
   */
  it('mostra de onde vem o saldo, mês a mês, fechando a conta', () => {
    montar();
    expect(screen.getByRole('heading', { name: 'De onde vem esse saldo' })).toBeInTheDocument();
    expect(screen.getByText('ago/2026')).toBeInTheDocument();
    expect(screen.getByText('você deve R$ 200,00')).toBeInTheDocument();
    expect(screen.getByText('jul/2026')).toBeInTheDocument();
    expect(screen.getByText('você deve R$ 120,00')).toBeInTheDocument();
    expect(screen.getByText('R$ 40,00 já acertados')).toBeInTheDocument();
    expect(screen.getByText('Total acumulado')).toBeInTheDocument();
    expect(screen.getByText('você deve R$ 320,00')).toBeInTheDocument();
  });

  /*
   * Saldo zero NÃO quer dizer mês nenhum em aberto: devo maio e tenho junho a
   * receber. Chamar aquilo de "de onde vem esse saldo" seria uma frase sem
   * referente.
   */
  it('com saldo zero e meses abertos, o título deixa de falar em saldo', () => {
    mockDebts.mockReturnValue({ debts: [], isLoading: false, isError: false, refetch: vi.fn() });
    mockOrigem.mockReturnValue({
      origem: {
        ...ORIGEM,
        balance: '0.00',
        months: [
          { month: '2026-08', balance: '-50.00', net_debts: [], settled: '0.00' },
          { month: '2026-07', balance: '50.00', net_debts: [], settled: '0.00' },
        ],
      },
      isLoading: false, isError: false, refetch: vi.fn(),
    });
    montar();
    expect(screen.getByText('Tudo certo')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Meses ainda não fechados' })).toBeInTheDocument();
    expect(screen.getByText('você recebe R$ 50,00')).toBeInTheDocument();
  });

  it('clicar num mês da origem abre a aba Por mês naquele mês', () => {
    montar();
    fireEvent.click(screen.getByText('jul/2026'));
    expect(screen.getByRole('tab', { name: 'Por mês' })).toHaveAttribute('data-state', 'active');
    // O navegador de mês acompanhou — se `tab` e `month` fossem escritos em duas
    // chamadas a `setSearchParams`, a segunda apagaria a primeira e o mês
    // continuaria em agosto.
    expect(screen.getByText('Julho de 2026')).toBeInTheDocument();
  });

  /*
   * O mês mostrava as linhas "fulano pagou X a beltrano" logo acima da tabela de
   * histórico, na mesma rolagem: o mesmo pagamento duas vezes. Agora mostra só o
   * estado, e manda para o histórico.
   */
  it('a aba do mês mostra o estado, não a lista de acertos', () => {
    montar();
    abrirAba('Por mês');
    expect(screen.getByText('R$ 40,00 já acertados')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'ver no histórico' })).toBeInTheDocument();
    expect(screen.getByText('Quem deve a quem neste mês')).toBeInTheDocument();
  });

  it('as despesas do mês vêm recolhidas, com o resumo na dobra', () => {
    montar();
    abrirAba('Por mês');
    const bloco = screen.getByText('Despesas do mês').closest('details')!;
    expect(bloco).not.toHaveAttribute('open');
    expect(screen.getByText(/1 · R\$ 400,00 · 1 em aberto/)).toBeInTheDocument();
  });

  /*
   * `billing_month` sempre existiu na resposta e nunca apareceu na tela — por
   * isso o acerto que fecha um mês era indistinguível do que só abate o
   * acumulado, e o saldo parecia cair sozinho.
   */
  it('o histórico marca o mês de cada acerto, inclusive os que não têm', () => {
    montar();
    abrirAba('Histórico');
    expect(screen.getByText('jul/2026')).toBeInTheDocument();
    expect(screen.getByText('sem mês')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Desfazer acerto' })).toHaveLength(2);
  });

  it('viewer não registra nem desfaz acerto (RBAC-FE-001)', () => {
    mockRole.mockReturnValue({ canWrite: false });
    montar();
    expect(screen.getByRole('button', { name: /Paguei/ })).toBeDisabled();
    abrirAba('Histórico');
    for (const b of screen.getAllByRole('button', { name: 'Desfazer acerto' })) {
      expect(b).toBeDisabled();
    }
  });

  /*
   * Regressão da auditoria: o hook devolvia `isError` e a tela não o lia, então
   * a quebra sumia em silêncio. Pior que a tela antiga — lá a ausência era o
   * normal; aqui ela se lê como "esse saldo não vem de mês nenhum".
   */
  it('falha na origem do saldo aparece, em vez de o bloco sumir (ERR-001)', () => {
    const refetch = vi.fn();
    mockOrigem.mockReturnValue({ origem: null, isLoading: false, isError: true, refetch });
    montar();

    expect(screen.getByText(/Não foi possível abrir a origem do saldo/)).toBeInTheDocument();
    // O título não pode virar "Meses ainda não fechados": sem resposta, ninguém
    // sabe se há mês em aberto.
    expect(screen.getByRole('heading', { name: 'De onde vem esse saldo' })).toBeInTheDocument();
    // O total do topo continua válido — ele vem da OUTRA consulta.
    expect(screen.getByText('Você deve, no total')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Tentar novamente' }));
    expect(refetch).toHaveBeenCalled();
  });

  /*
   * O histórico do espaço pintava TODA linha de verde, inclusive as que eu
   * paguei. Verde ali quer dizer "entrou para mim", e num acerto que eu paguei
   * isso é o inverso do que aconteceu.
   */
  it('o valor do histórico segue a direção de quem olha', () => {
    montar();
    abrirAba('Histórico');
    const linhas = screen.getAllByText(/R\$ (40|15),00/);
    // Os dois acertos do cenário saíram de mim → sinal negativo e cor de saída.
    for (const v of linhas) {
      expect(v.textContent).toMatch(/^−/);
      expect(v.className).toContain('text-expense');
    }
    expect(screen.getAllByText('Você')).not.toHaveLength(0);
  });

  it('o histórico não diz "nenhum acerto" enquanto ainda carrega', () => {
    mockSettlements.mockReturnValue({
      settlements: [], isLoading: true, create: vi.fn(), remove: vi.fn(), isMutating: false,
    });
    montar();
    abrirAba('Histórico');
    expect(screen.queryByText('Nenhum acerto registrado ainda.')).not.toBeInTheDocument();
  });

  it('falha de API não vira "você não deve nada" (ERR-001)', () => {
    const refetch = vi.fn();
    mockDebts.mockReturnValue({ debts: [], isLoading: false, isError: true, refetch });
    montar();
    expect(screen.getByText(/Não foi possível carregar as dívidas/)).toBeInTheDocument();
    expect(screen.queryByRole('tab')).not.toBeInTheDocument();
  });

  it('a dívida entre terceiros fica no bloco dela, recolhida', () => {
    montar();
    const bloco = screen.getByText(/Entre outras pessoas/).closest('details')!;
    expect(bloco).not.toHaveAttribute('open');
    expect(within(bloco).getByText('Bruno')).toBeInTheDocument();
    expect(within(bloco).getByText('R$ 45,00')).toBeInTheDocument();
  });
});
