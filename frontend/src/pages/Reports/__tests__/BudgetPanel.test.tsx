import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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

  it('separa a meta da casa da meta pessoal', async () => {
    server.use(
      http.get(`${API}/workspaces/`, () =>
        HttpResponse.json([{ id: 1, name: 'Casa', base_currency: 'BRL' }]),
      ),
      http.get(`${API}/workspaces/1/categories`, () => HttpResponse.json([])),
      http.get(`${API}/workspaces/1/analytics/estimates`, () =>
        HttpResponse.json([
          {
            id: 1, category: 'Geral', amount: '1000.00', month: '2026-08',
            category_id: null, owner_user_id: null, scope: 'workspace',
          },
          {
            id: 2, category: 'Geral', amount: '500.00', month: '2026-08',
            category_id: null, owner_user_id: 7, scope: 'personal',
          },
        ]),
      ),
    );

    // A casa gastou 1000; a MINHA parte foi 500. Com uma meta só, o Início
    // marcava 50% do orçamento da casa enquanto Relatórios marcava 100%.
    render(
      <BudgetPanel
        spentByCategory={[]}
        totalExpenses={1000}
        mySpentByCategory={[]}
        myExpenses={500}
        month="2026-08"
      />,
      { wrapper },
    );

    // Aba "Da casa": 1000 de 1000
    expect(await screen.findByText(/1\.000,00.*de.*1\.000,00/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: 'Minha' }));

    // Aba "Minha": 500 de 500 — cada uma fecha com o próprio recorte
    expect(await screen.findByText(/500,00.*de.*500,00/)).toBeInTheDocument();
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

  /*
   * A observação da meta. O agente de IA a grava ("sem delivery este mês"); a
   * tela não a mostrava, e redefinir o valor pela tela a apagava. E não havia
   * como editar uma meta: só excluir e criar de novo.
   */
  it('mostra a observação e edita a meta mantendo-a', async () => {
    let corpo: Record<string, unknown> | null = null;
    server.use(
      http.get(`${API}/workspaces/`, () =>
        HttpResponse.json([{ id: 1, name: 'Casa', base_currency: 'BRL' }]),
      ),
      http.get(`${API}/workspaces/1/categories`, () => HttpResponse.json([{ id: 7, name: 'Mercado' }])),
      http.get(`${API}/workspaces/1/analytics/estimates`, () =>
        HttpResponse.json([{
          id: 3, category: 'Mercado', amount: '800.00', month: '2026-08', category_id: 7,
          owner_user_id: null, scope: 'workspace', description: 'Sem delivery este mês',
        }]),
      ),
      http.put(`${API}/workspaces/1/analytics/estimates/3`, async ({ request }) => {
        corpo = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: 3, ...corpo });
      }),
    );
    render(
      <BudgetPanel spentByCategory={[{ category_id: 7, name: 'Mercado', value: 100 }]} totalExpenses={100} month="2026-08" />,
      { wrapper },
    );

    expect(await screen.findByText('Sem delivery este mês')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Editar orçamento de Mercado' }));
    expect((screen.getByLabelText('Observação (opcional)') as HTMLInputElement).value).toBe('Sem delivery este mês');
    expect((screen.getByLabelText('Categoria') as HTMLSelectElement).value).toBe('7');
    fireEvent.change(screen.getByLabelText('Meta do mês'), { target: { value: '900,00' } });
    fireEvent.click(screen.getByRole('button', { name: 'Salvar' }));

    await waitFor(() => expect(corpo).not.toBeNull());
    expect(corpo).toMatchObject({ category_id: 7, amount: '900', description: 'Sem delivery este mês' });
  });
});
