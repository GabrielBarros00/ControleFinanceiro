import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/setup';
import { MerchantSpendingPanel } from '../MerchantSpendingPanel';

/**
 * Gasto por estabelecimento (ADR 0038): valor cheio e sua parte lado a lado, o
 * mês pedido chega ao servidor, e só o que tem estabelecimento leva à lista.
 */
const API = 'http://localhost:8000/api/v1';
vi.mock('@/hooks/use-workspace-id', () => ({ useWorkspaceId: () => 7 }));

function renderizar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <MerchantSpendingPanel month="2026-09" workspaceId={7} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('MerchantSpendingPanel', () => {
  it('mostra o valor cheio e a sua parte, e liga o estabelecimento à lista do mês', async () => {
    let mes: string | null = null;
    server.use(http.get(`${API}/workspaces/7/merchants/spending`, ({ request }) => {
      mes = new URL(request.url).searchParams.get('month');
      return HttpResponse.json([
        { id: 3, name: 'Mercado Lela', currency: 'BRL', total: '300.00', my_share: '150.00', count: 4 },
        { id: null, name: 'Sem estabelecimento', currency: 'BRL', total: '80.00', my_share: '80.00', count: 2 },
      ]);
    }));
    renderizar();
    const linha = (await screen.findByRole('link', { name: 'Mercado Lela' })).closest('tr')!;
    expect(mes).toBe('2026-09');
    expect(within(linha).getByRole('link')).toHaveAttribute('href', '/w/7/transactions?estabelecimento=3&month=2026-09');
    // Valor cheio: coluna no desktop e "de R$ X" debaixo do nome no celular.
    expect(within(linha).getAllByText(/300,00/)).toHaveLength(2);
    expect(within(linha).getByText(/150,00/)).toBeInTheDocument();
    const sem = screen.getByText('Sem estabelecimento').closest('tr')!;
    expect(within(sem).queryByRole('link')).not.toBeInTheDocument();
  });

  it('mês sem gasto diz isso, e não uma tabela vazia', async () => {
    server.use(http.get(`${API}/workspaces/7/merchants/spending`, () => HttpResponse.json([])));
    renderizar();
    expect(await screen.findByText('Nenhum gasto neste mês.')).toBeInTheDocument();
  });
});
