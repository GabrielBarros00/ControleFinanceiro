import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, it, expect, beforeEach } from 'vitest';
import { server } from '@/test/setup';
import { useUIStore } from '@/stores';
import { BudgetPanel } from '../BudgetPanel';

const API = 'http://localhost:8000/api/v1';

const wrapper = ({ children }: { children: React.ReactNode }) => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
};

function backend(baseCurrency = 'BRL') {
  server.use(
    http.get(`${API}/workspaces/`, () =>
      HttpResponse.json([{ id: 1, name: 'Casa', base_currency: baseCurrency }]),
    ),
    http.get(`${API}/workspaces/1/analytics/estimates`, () => HttpResponse.json([])),
    http.get(`${API}/workspaces/1/categories`, () => HttpResponse.json([])),
  );
}

describe('BudgetPanel', () => {
  beforeEach(() => {
    useUIStore.getState().setCurrentWorkspaceId(1);
  });

  it('formata na moeda-base do workspace, não em R$ fixo', async () => {
    backend('USD');
    render(
      <BudgetPanel
        spentByCategory={[{ category_id: 1, name: 'Mercado', value: 100 }]}
        totalExpenses={100}
        month="2026-08"
      />,
      { wrapper },
    );

    // Antes o componente tinha um formatBRL local com "R$" no código, e num
    // workspace em USD os números vinham certos com o símbolo errado.
    await waitFor(() => {
      expect(screen.queryByText(/R\$/)).not.toBeInTheDocument();
    });
  });

  it('avisa quando há lançamentos fora da moeda-base', async () => {
    backend();
    render(
      <BudgetPanel
        spentByCategory={[]}
        totalExpenses={0}
        excludedForeignCount={3}
        month="2026-08"
      />,
      { wrapper },
    );

    // O backend calculava excluded_foreign_count em dois serviços e nenhuma
    // tela lia o campo: os totais excluíam lançamentos em silêncio.
    expect(await screen.findByRole('status')).toHaveTextContent(/3 lançamentos/i);
  });

  it('não mostra o aviso quando não há exclusão', async () => {
    backend();
    render(
      <BudgetPanel spentByCategory={[]} totalExpenses={0} excludedForeignCount={0} month="2026-08" />,
      { wrapper },
    );

    await waitFor(() => {
      expect(screen.getByText(/Orçamento por Categoria/i)).toBeInTheDocument();
    });
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});
