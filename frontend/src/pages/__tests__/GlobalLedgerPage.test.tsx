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
});
