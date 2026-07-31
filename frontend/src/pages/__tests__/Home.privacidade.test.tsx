import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { Home } from '../Home';

/**
 * Painel do workspace: privacidade (ADR 0018) e escopo (ADR 0021).
 *
 * O backend devolve `null` nos números da CASA para quem é `involved_only`. O
 * painel lia com `?? 0`, e é aí que estava o defeito de apresentação: mostraria
 * "Gasto da casa R$ 0,00" ao lado da despesa real do membro — um número
 * INVENTADO na tela, mais enganoso do que não mostrar nada.
 *
 * O segundo eixo é o que este painel NÃO pode mais dizer. "Sua receita" e
 * "Resultado do mês" eram renda GLOBAL da pessoa combinada com a despesa DESTE
 * workspace — o número que dava "sobras" diferentes e todas maiores que a real
 * em cada casa. Renda e resultado vivem na Visão global.
 *
 * O terceiro é o `canWrite`: o painel era justamente a tela que renderizava o
 * ledger sem a prop, e o default permissivo mostrava editar/excluir a um viewer.
 */

const RESUMO_RESTRITO = {
  // Números da casa suprimidos pelo servidor
  total_expenses: null,
  categories: null,
  // O recorte pessoal continua vindo
  my_expenses: '100.00',
  paid_by_me: '0.00',
  my_balance: '-100.00',
  my_categories: [],
  base_currency: 'BRL',
  excluded_foreign_count: 0,
};

const RESUMO_COMPLETO = {
  ...RESUMO_RESTRITO,
  total_expenses: '900.00',
  paid_by_me: '900.00',
  my_balance: '800.00',
  categories: [],
};

const estado = {
  resumo: RESUMO_RESTRITO as Record<string, unknown>,
  canWrite: false,
};

vi.mock('@/hooks/use-reports', () => ({
  useReports: () => ({ data: { current_summary: estado.resumo }, isLoading: false }),
}));
vi.mock('@/hooks/use-analytics', () => ({
  useAnalytics: () => ({ forecast: { my_budget: '500.00' }, isLoading: false }),
}));
vi.mock('@/hooks/use-transactions', () => ({
  useTransactions: () => ({ transactions: [], isLoading: false }),
}));
vi.mock('@/hooks/use-base-currency', () => ({
  useBaseCurrency: () => 'BRL',
}));
vi.mock('@/hooks/use-workspaces', () => ({
  useWorkspaces: () => ({ currentWorkspace: { id: 1, name: 'Casa' } }),
}));
vi.mock('@/hooks/use-workspace-role', () => ({
  useWorkspaceRole: () => ({ canWrite: estado.canWrite, isLoading: false }),
}));

function renderHome() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Home />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Painel do workspace — acesso financeiro restrito', () => {
  beforeEach(() => {
    estado.resumo = RESUMO_RESTRITO;
    estado.canWrite = false;
  });

  it('não inventa "Gasto da casa R$ 0,00" quando o total vem nulo', () => {
    renderHome();
    expect(screen.queryByText('Gasto da casa')).not.toBeInTheDocument();
  });

  it('mostra a própria parte mesmo sem os números da casa', () => {
    renderHome();
    expect(screen.getByText('Sua parte no mês')).toBeInTheDocument();
    expect(screen.getByText('Pago por você')).toBeInTheDocument();
  });

  it('não fala de renda nem de sobra — isso é da Visão global', () => {
    estado.resumo = RESUMO_COMPLETO;
    renderHome();
    expect(screen.queryByText(/receita/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/sobra/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/resultado do mês/i)).not.toBeInTheDocument();
  });

  it('nomeia o acerto pelo lado em que a pessoa está', () => {
    renderHome(); // my_balance negativo: consumiu 100 e não pagou nada
    expect(screen.getByText('Você deve')).toBeInTheDocument();

    estado.resumo = RESUMO_COMPLETO; // pagou 900, consumiu 100
    renderHome();
    expect(screen.getByText('Você tem a receber')).toBeInTheDocument();
  });

  it('esconde "Nova despesa" de quem não pode escrever', () => {
    renderHome();
    expect(screen.queryByRole('button', { name: /nova despesa/i })).not.toBeInTheDocument();
  });

  it('mostra "Nova despesa" para quem pode escrever', () => {
    estado.canWrite = true;
    renderHome();
    expect(screen.getAllByRole('button', { name: /nova despesa/i }).length).toBeGreaterThan(0);
  });

  it('com acesso completo, o gasto da casa aparece com a sua parte na dica', () => {
    estado.resumo = RESUMO_COMPLETO;
    renderHome();
    expect(screen.getByText('Gasto da casa')).toBeInTheDocument();
    expect(screen.getByText(/^Sua parte: /)).toBeInTheDocument();
  });
});
