import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@/test/utils';
import { ReportsPage } from '../ReportsPage';

/**
 * "Maior categoria: Sem categoria".
 *
 * Era o quadro mais honesto e mais inútil da tela. Numa conta de uso real ele
 * diz que a maior fatia do mês é a ausência de classificação — quer dizer, que
 * os relatórios não têm o que relatar — e parava aí. Um quarto da faixa de
 * destaque gasto para constatar um problema sem oferecer a saída, que é a
 * definição de métrica que não vira ação.
 *
 * Agora ele leva à lista do que falta categorizar. O filtro `?semcategoria=sim`
 * existe do backend (`uncategorized`) à URL justamente para este link ter para
 * onde apontar — antes não havia como pedir "as despesas sem categoria" à API.
 *
 * O valor entrou junto por outro motivo: "Mercado" sozinho não diz se são R$ 80
 * ou R$ 1.800, e é o tamanho que faz alguém agir.
 */
const RESUMO = (categorias: { name: string; value: number }[]) => ({
  current_summary: {
    total_expenses: 1000, my_expenses: 500, paid_by_me: 500, my_balance: 0,
    categories: categorias, my_categories: categorias,
  },
  monthly_history: [],
});

const mockReports = vi.fn();
vi.mock('@/hooks/use-reports', () => ({ useReports: () => mockReports() }));
vi.mock('@/hooks/use-base-currency', () => ({ useBaseCurrency: () => 'BRL' }));
vi.mock('@/hooks/use-chart-theme', () => ({
  useChartTheme: () => ({ grid: '#eee', axis: '#999', tooltip: {}, series: ['#123456'] }),
}));
vi.mock('@/stores', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  useUIStore: () => ({ currentWorkspaceId: 7 }),
}));

function desenhar(categorias: { name: string; value: number }[]) {
  mockReports.mockReturnValue({ data: RESUMO(categorias), isLoading: false });
  return render(<ReportsPage />);
}

describe('Relatórios — quadro "Maior categoria"', () => {
  it('convida a categorizar quando a maior fatia é a falta de categoria', () => {
    desenhar([{ name: 'Sem categoria', value: 800 }, { name: 'Mercado', value: 200 }]);

    const convite = screen.getByRole('link', { name: /categorizar estas despesas/i });
    expect(convite).toHaveAttribute(
      'href',
      expect.stringContaining('/w/7/transactions?semcategoria=sim'),
    );
  });

  it('mostra o tamanho da categoria, não só o nome', () => {
    desenhar([{ name: 'Mercado', value: 812.5 }]);

    expect(screen.getByText('Mercado')).toBeInTheDocument();
    expect(screen.getByText(/812,50/)).toBeInTheDocument();
  });

  it('não convida quando não há nada para categorizar', () => {
    // Controle: o convite tem de ser exceção. Um link que aparece sempre vira
    // parte do cenário e ninguém mais o vê.
    desenhar([{ name: 'Mercado', value: 800 }, { name: 'Transporte', value: 200 }]);

    expect(screen.queryByRole('link', { name: /categorizar/i })).toBeNull();
  });
});
