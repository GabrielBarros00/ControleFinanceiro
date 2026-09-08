import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ReportsPage } from '../ReportsPage';

/**
 * A aba Categorias — de quem são aqueles números.
 *
 * A pizza e o ranking sempre foram do ESPAÇO para quem tem acesso financeiro
 * completo, e nada na tela dizia isso: ficavam sob um cabeçalho cujo primeiro
 * número é "Seu gasto (mês)". Quem divide o aluguel lia "Moradia R$ 8.450" como
 * seu. `my_categories` já vinha no mesmo payload — é o que a tela usa quando o
 * acesso é restrito —, só não havia como escolher.
 */
const RESUMO = {
  total_expenses: '1000.00',
  my_expenses: '400.00',
  paid_by_me: '1000.00',
  my_balance: '600.00',
  categories: [
    { category_id: 1, name: 'Moradia', value: 800 },
    { category_id: 2, name: 'Mercado', value: 200 },
  ],
  my_categories: [
    { category_id: 1, name: 'Moradia', value: 300 },
    { category_id: 2, name: 'Mercado', value: 100 },
  ],
  base_currency: 'BRL',
  excluded_foreign_count: 0,
};

const mockReports = vi.fn();

vi.mock('@/hooks/use-reports', () => ({ useReports: () => mockReports() }));
vi.mock('@/hooks/use-base-currency', () => ({ useBaseCurrency: () => 'BRL' }));
vi.mock('@/hooks/use-analytics', () => ({
  useAnalytics: () => ({ forecast: null, isLoading: false }),
}));
// O painel de orçamento tem consultas próprias; aqui a pergunta é outra aba.
vi.mock('../BudgetPanel', () => ({ BudgetPanel: () => null }));

function montar(resumo: Record<string, unknown> = RESUMO) {
  mockReports.mockReturnValue({
    data: { current_summary: resumo, monthly_history: [] },
    isLoading: false,
    isError: false,
  });
  return render(
    <MemoryRouter initialEntries={['/w/1/reports?month=2026-08']}>
      <ReportsPage />
    </MemoryRouter>,
  );
}

/** Radix ativa a aba no `mousedown`; ver `AdminPage.test.tsx`. */
function abrirAba(nome: string) {
  const gatilho = screen.getByRole('tab', { name: nome });
  fireEvent.mouseDown(gatilho);
  fireEvent.click(gatilho);
}

describe('Relatórios — a composição por categoria', () => {
  it('anuncia que a composição é do espaço, e não da sua parte', () => {
    montar();
    abrirAba('Categorias');
    expect(screen.getByText('Distribuição do espaço')).toBeInTheDocument();
    expect(screen.getByText('Gastos do espaço')).toBeInTheDocument();
    expect(screen.getByText(/inclui o que é das outras pessoas/)).toBeInTheDocument();
    expect(screen.getByText(/Total: R\$ 1\.000,00/)).toBeInTheDocument();
  });

  it('deixa trocar para a sua fatia de cada despesa', () => {
    montar();
    abrirAba('Categorias');
    fireEvent.click(screen.getByRole('button', { name: 'Sua parte' }));

    expect(screen.getByText('Sua distribuição por categoria')).toBeInTheDocument();
    expect(screen.getByText('Gastos da sua parte')).toBeInTheDocument();
    // 300 + 100 — os números de `my_categories`, não os da casa.
    expect(screen.getByText(/Total: R\$ 400,00/)).toBeInTheDocument();
    // O mesmo valor aparece no quadro "Maior categoria" da faixa de destaque:
    // o recorte é a lista da aba, que é o que este teste está examinando.
    expect(within(screen.getByRole('list', { name: /categorias/i }))
      .getByText('R$ 300,00')).toBeInTheDocument();
    expect(screen.queryByText('R$ 800,00')).not.toBeInTheDocument();
  });

  /*
   * Sem acesso financeiro completo (ADR 0018) a casa vem `null` e só existe a
   * própria visão. Dois botões em que um nunca pode ser clicado ensinam a coisa
   * errada sobre o que a pessoa poderia ver.
   */
  it('sem acesso à casa, não oferece uma escolha que não existe', () => {
    montar({ ...RESUMO, total_expenses: null, categories: null });
    abrirAba('Categorias');
    expect(screen.queryByRole('group', { name: 'De quem é a composição' })).not.toBeInTheDocument();
    expect(screen.getByText('Sua distribuição por categoria')).toBeInTheDocument();
    expect(within(screen.getByRole('list', { name: /categorias/i }))
      .getByText('R$ 300,00')).toBeInTheDocument();
  });
});
