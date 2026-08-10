import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { GlobalLedgerPage } from '../GlobalLedgerPage';

/**
 * Extrato global.
 *
 * A razão de existir: a Visão global dizia "saiu R$ 4.200" e mostrava a origem,
 * mas não havia como chegar às LINHAS. Aqui elas aparecem — com a data efetiva
 * (ADR 0022), a origem, o workspace e, quando o movimento foi em outra moeda, o
 * valor original ao lado do convertido.
 */
const LEDGER = {
  currency: 'BRL',
  month: '2026-07',
  total: 3,
  cash_in: '5000.00',
  cash_out: '420.00',
  net_cash: '4580.00',
  excluded_foreign_count: 0,
  entries: [
    {
      source: 'income', direction: 'in', occurred_on: '2026-07-20',
      amount: '5000.00', currency: 'BRL', converted_amount: '5000.00',
      title: 'Salário', workspace_id: null, workspace_name: null,
      card_id: null, financing_id: null, counterparty_id: null,
      counterparty_name: null, reference_id: 1,
    },
    {
      source: 'statement_payment', direction: 'out', occurred_on: '2026-07-15',
      amount: '300.00', currency: 'BRL', converted_amount: '300.00',
      title: 'Nubank — fatura de 2026-07', workspace_id: null, workspace_name: null,
      card_id: 9, financing_id: null, counterparty_id: null,
      counterparty_name: null, reference_id: 2,
    },
    {
      source: 'settlement_sent', direction: 'out', occurred_on: '2026-07-10',
      amount: '120.00', currency: 'BRL', converted_amount: '120.00',
      title: 'Acerto enviado', workspace_id: 1, workspace_name: 'Casa',
      card_id: null, financing_id: null, counterparty_id: 2,
      counterparty_name: 'Vizinho', reference_id: 3,
    },
  ],
};

const SEM_COTACAO = {
  ...LEDGER,
  excluded_foreign_count: 1,
  entries: [
    {
      ...LEDGER.entries[1],
      amount: '100.00', currency: 'USD', converted_amount: null,
    },
  ],
};

const mockLedger = vi.fn();
vi.mock('@/hooks/use-overview', () => ({
  useLedger: (...args: unknown[]) => mockLedger(...args),
}));
vi.mock('@/hooks/use-workspaces', () => ({
  useWorkspaces: () => ({ workspaces: [{ id: 1, name: 'Casa' }, { id: 2, name: 'Viagem' }] }),
}));
vi.mock('@/hooks/use-credit-cards', () => ({
  useCreditCards: () => ({
    cards: [
      { id: 9, name: 'Nubank', currency: 'BRL' },
      { id: 10, name: 'Inter', currency: 'BRL' },
    ],
  }),
}));

function renderPage(ledger: unknown = LEDGER, rota = '/me/ledger?month=2026-07') {
  mockLedger.mockReturnValue({ ledger, isLoading: false });
  return render(
    <MemoryRouter initialEntries={[rota]}>
      <GlobalLedgerPage />
    </MemoryRouter>,
  );
}

describe('Extrato global', () => {
  beforeEach(() => mockLedger.mockReset());

  it('lista os movimentos com data, origem e contraparte', () => {
    renderPage();
    expect(screen.getByText('Salário')).toBeInTheDocument();
    expect(screen.getByText('Nubank — fatura de 2026-07')).toBeInTheDocument();
    expect(screen.getByText('· Vizinho')).toBeInTheDocument();
    // "Casa" está na tabela E na <option> do filtro — escopa na tabela.
    const tabela = screen.getByRole('table');
    expect(within(tabela).getByText('Casa')).toBeInTheDocument();
    expect(within(tabela).getByText('Rendas')).toBeInTheDocument();
  });

  it('mostra entrada, saída e saldo do mês', () => {
    renderPage();
    expect(screen.getByText('Entrou')).toBeInTheDocument();
    expect(screen.getByText('Saiu')).toBeInTheDocument();
    expect(screen.getByText('Saldo do mês')).toBeInTheDocument();
  });

  it('lê o filtro de origem da URL e o repassa ao hook', () => {
    renderPage(LEDGER, '/me/ledger?month=2026-07&source=income');
    expect(mockLedger).toHaveBeenCalledWith(
      expect.objectContaining({ source: ['income'], month: '2026-07' }),
    );
    expect(screen.getByRole('button', { name: 'Rendas' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('alternar uma origem muda o recorte', () => {
    renderPage();
    expect(screen.getByRole('button', { name: 'Faturas' })).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(screen.getByRole('button', { name: 'Faturas' }));
    expect(screen.getByRole('button', { name: 'Faturas' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('filtra por workspace quando há mais de um', () => {
    renderPage();
    const seletor = screen.getByLabelText('Filtrar por workspace');
    fireEvent.change(seletor, { target: { value: '2' } });
    expect(mockLedger).toHaveBeenLastCalledWith(
      expect.objectContaining({ workspace_id: 2 }),
    );
  });

  it('movimento sem cotação aparece MARCADO, não some nem vira zero', () => {
    renderPage(SEM_COTACAO);
    // A política do ADR 0006: omitir da soma, mas mostrar e contar.
    expect(screen.getByTitle('Sem cotação para esta data')).toBeInTheDocument();
  });

  it('mês vazio explica que não houve movimento', () => {
    renderPage({ ...LEDGER, entries: [], total: 0 });
    expect(screen.getByText('Nenhum movimento neste recorte')).toBeInTheDocument();
  });

  it('com filtro ativo, o vazio sugere limpá-lo', () => {
    renderPage({ ...LEDGER, entries: [], total: 0 }, '/me/ledger?source=income');
    expect(screen.getByText(/Limpe-os para ver o mês inteiro/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Limpar filtros' })).toBeInTheDocument();
  });

  it('filtra por cartão quando há mais de um', () => {
    renderPage();
    fireEvent.change(screen.getByLabelText('Filtrar por cartão'), { target: { value: '9' } });
    expect(mockLedger).toHaveBeenLastCalledWith(
      expect.objectContaining({ card_id: 9 }),
    );
  });
});

/**
 * Paginação.
 *
 * A tela fixava `limit: 200` e, passando disso, mandava "use os filtros para
 * estreitar o recorte" — que não é resposta para quem tem mais de 200
 * movimentos no mês: o resto do extrato ficava inalcançável. O backend sempre
 * aceitou `limit`/`offset`.
 */
describe('Extrato global — paginação', () => {
  beforeEach(() => mockLedger.mockReset());

  const MUITOS = { ...LEDGER, total: 312 };

  it('pede a primeira página com limite e offset', () => {
    renderPage(MUITOS);
    expect(mockLedger).toHaveBeenCalledWith(
      expect.objectContaining({ limit: 100, offset: 0 }),
    );
  });

  it('mostra o intervalo e o total, não só "mostrando N de M"', () => {
    renderPage(MUITOS);
    expect(screen.getByText(/Mostrando 1–3 de 312 movimentos/)).toBeInTheDocument();
  });

  it('a página vem da URL — o recorte é compartilhável', () => {
    renderPage(MUITOS, '/me/ledger?month=2026-07&page=2');
    expect(mockLedger).toHaveBeenCalledWith(
      expect.objectContaining({ offset: 200 }),
    );
    expect(screen.getByText(/Mostrando 201–203 de 312/)).toBeInTheDocument();
  });

  it('"Anterior" fica desabilitado na primeira página', () => {
    renderPage(MUITOS);
    expect(screen.getByRole('button', { name: 'Anterior' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Próxima' })).toBeEnabled();
  });

  it('"Próxima" fica desabilitado na última página', () => {
    renderPage(MUITOS, '/me/ledger?month=2026-07&page=3');
    expect(screen.getByRole('button', { name: 'Próxima' })).toBeDisabled();
  });

  it('avançar muda o offset pedido', () => {
    renderPage(MUITOS);
    fireEvent.click(screen.getByRole('button', { name: 'Próxima' }));
    expect(mockLedger).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 100 }),
    );
  });

  it('trocar de filtro volta para a primeira página', () => {
    renderPage(MUITOS, '/me/ledger?month=2026-07&page=2');
    fireEvent.click(screen.getByRole('button', { name: 'Faturas' }));
    expect(mockLedger).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 0 }),
    );
  });

  it('cabendo numa página, não há paginador', () => {
    renderPage(LEDGER);
    expect(screen.queryByRole('button', { name: 'Próxima' })).not.toBeInTheDocument();
  });
});
