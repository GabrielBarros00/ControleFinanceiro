import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { MyReportsPage } from '../MyReportsPage';

/**
 * Os dois gráficos têm limiares DIFERENTES.
 *
 * O defeito: uma única condição ("pelo menos dois meses com movimento")
 * controlava os dois. Um mês com valores é insuficiente para desenhar uma
 * tendência — a linha vira um ponto solto —, mas é perfeitamente comparável em
 * barras. Na aplicação real havia valores no mês e o gráfico de "Renda ×
 * consumo" exibia "ainda não há meses suficientes".
 */
const UM_MES = {
  currency: 'BRL',
  months: [
    { month: '2026-07', income: '5000.00', consumption: '900.00', result: '4100.00', cash_in: '5000.00', cash_out: '900.00', net_cash: '4100.00' },
  ],
  totals: { income: '5000.00', consumption: '900.00', result: '4100.00', cash_in: '5000.00', cash_out: '900.00', net_cash: '4100.00' },
  by_workspace: [{ workspace_id: 1, workspace_name: 'Casa', consumption: '900.00' }],
  excluded_foreign_count: 0,
};

const DOIS_MESES = {
  ...UM_MES,
  months: [
    { month: '2026-06', income: '5000.00', consumption: '800.00', result: '4200.00', cash_in: '5000.00', cash_out: '800.00', net_cash: '4200.00' },
    ...UM_MES.months,
  ],
};

const SEM_MOVIMENTO = {
  ...UM_MES,
  months: [
    { month: '2026-07', income: '0.00', consumption: '0.00', result: '0.00', cash_in: '0.00', cash_out: '0.00', net_cash: '0.00' },
  ],
};

const mockReports = vi.fn();
vi.mock('@/hooks/use-overview', () => ({
  useMyReports: (...args: unknown[]) => mockReports(...args),
}));

// Recharts não mede num jsdom sem layout; o conteúdo dos gráficos não é o que
// está sob teste — a presença deles é.
vi.mock('@/hooks/use-chart-theme', () => ({
  useChartTheme: () => ({
    grid: '#eee', axis: '#999', tooltip: {}, series: ['#a', '#b'], legend: {},
  }),
}));

function renderPage(reports: unknown, rota = '/me/reports') {
  mockReports.mockReturnValue({ reports, isLoading: false });
  return render(
    <MemoryRouter initialEntries={[rota]}>
      <MyReportsPage />
    </MemoryRouter>,
  );
}

describe('Seus relatórios — limiares dos gráficos', () => {
  it('com UM mês de movimento, compara renda × consumo', () => {
    renderPage(UM_MES);
    expect(screen.getByText('Renda × consumo')).toBeInTheDocument();
    expect(screen.queryByText('Nenhum movimento no período')).not.toBeInTheDocument();
  });

  it('com UM mês, ainda não desenha a tendência', () => {
    renderPage(UM_MES);
    expect(screen.getByText('Ainda não dá para desenhar a evolução')).toBeInTheDocument();
  });

  it('com DOIS meses, desenha as duas', () => {
    renderPage(DOIS_MESES);
    expect(screen.queryByText('Ainda não dá para desenhar a evolução')).not.toBeInTheDocument();
    expect(screen.queryByText('Nenhum movimento no período')).not.toBeInTheDocument();
  });

  it('sem movimento nenhum, avisa em vez de desenhar um gráfico vazio', () => {
    renderPage(SEM_MOVIMENTO);
    expect(screen.getByText('Nenhum movimento no período')).toBeInTheDocument();
  });
});

describe('Seus relatórios — período', () => {
  it('usa 6 meses por padrão', () => {
    renderPage(DOIS_MESES);
    expect(mockReports).toHaveBeenCalledWith(6);
    expect(screen.getByText(/Últimos 6 meses/)).toBeInTheDocument();
  });

  it('respeita o período vindo da URL', () => {
    renderPage(DOIS_MESES, '/me/reports?months=12');
    expect(mockReports).toHaveBeenCalledWith(12);
    expect(screen.getByText(/Últimos 12 meses/)).toBeInTheDocument();
  });

  it('ignora período fora da lista e volta ao padrão', () => {
    // A API aceita 1..12; um valor arbitrário na URL não pode virar um pedido
    // inválido nem uma tela quebrada.
    renderPage(DOIS_MESES, '/me/reports?months=999');
    expect(mockReports).toHaveBeenCalledWith(6);
  });

  it('oferece os três períodos, com o atual marcado', () => {
    renderPage(DOIS_MESES, '/me/reports?months=3');
    const grupo = screen.getByRole('group', { name: 'Período do relatório' });
    expect(grupo).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '3m' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: '6m' })).toHaveAttribute('aria-pressed', 'false');
  });
});
