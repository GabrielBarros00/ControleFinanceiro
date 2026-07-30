import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { Home } from '../Home';

/**
 * Início com acesso financeiro RESTRITO (ADR 0018).
 *
 * O backend passou a devolver `null` nos números da CASA para quem é
 * `involved_only`. O Início lia com `?? 0`, e é aí que estava o defeito de
 * apresentação: a dica renderizaria "Casa R$ 0,00" ao lado da despesa real do
 * membro — um número INVENTADO na tela, mais enganoso do que não mostrar nada.
 *
 * O outro caso é o `canWrite`: o Início era justamente a tela que renderizava o
 * ledger sem a prop, e o default permissivo dos componentes mostrava
 * editar/excluir a um viewer.
 */

const RESUMO_RESTRITO = {
  // Números da casa suprimidos pelo servidor
  total_expenses: null,
  total_income: null,
  net_savings: null,
  categories: null,
  // O recorte pessoal continua vindo
  my_expenses: '100.00',
  my_income: '3000.00',
  my_net: '2900.00',
  my_categories: [],
  base_currency: 'BRL',
  excluded_foreign_count: 0,
};

const RESUMO_COMPLETO = {
  ...RESUMO_RESTRITO,
  total_expenses: '900.00',
  total_income: '12000.00',
  net_savings: '11100.00',
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
vi.mock('@/hooks/use-auth', () => ({
  useAuth: () => ({ user: { id: 1, name: 'Bia' } }),
}));
vi.mock('@/hooks/use-base-currency', () => ({
  useBaseCurrency: () => 'BRL',
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

describe('Início — acesso financeiro restrito', () => {
  beforeEach(() => {
    estado.resumo = RESUMO_RESTRITO;
    estado.canWrite = false;
  });

  it('não inventa "Casa R$ 0,00" quando o total da casa vem nulo', () => {
    renderHome();
    expect(screen.queryByText(/Casa/)).not.toBeInTheDocument();
  });

  it('mostra a própria parte mesmo sem os números da casa', () => {
    renderHome();
    // A receita pessoal continua na tela: é dado do próprio usuário
    expect(screen.getByText('Sua receita')).toBeInTheDocument();
    expect(screen.getByText('Sua despesa')).toBeInTheDocument();
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

  it('com acesso completo, a dica da casa volta a aparecer', () => {
    estado.resumo = RESUMO_COMPLETO;
    renderHome();
    // Os totais da casa DIFEREM da parte pessoal, então a dica é informativa
    expect(screen.getAllByText(/^Casa /).length).toBeGreaterThan(0);
  });
});
