import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/setup';
import { ConfirmProvider } from '@/components/ui/confirm';
import { MerchantsTab } from '../MerchantsTab';

/**
 * Aba "Estabelecimentos" (ADR 0038). O que ela não pode errar: mandar os
 * apelidos como lista, mesclar no estabelecimento ESCOLHIDO (e só depois do
 * "sim"), levar à lista filtrada, e não oferecer escrita a quem só lê.
 */
const API = 'http://localhost:8000/api/v1';
const mockRole = vi.hoisted(() => vi.fn(() => ({ canWrite: true, isAdmin: false, isOwner: false, role: 'member', isLoading: false })));
vi.mock('@/hooks/use-workspace-role', () => ({ useWorkspaceRole: () => mockRole() }));
vi.mock('@/hooks/use-workspace-id', () => ({ useWorkspaceId: () => 7 }));

const LISTA = [
  { id: 1, name: "McDonald's", aliases: ['ifd mc donalds'], default_category_id: 5, transaction_count: 3 },
  { id: 2, name: 'MC DONALDS', aliases: [], default_category_id: null, transaction_count: 1 },
];
const recebidos: Array<{ metodo: string; url: string; corpo: unknown }> = [];

function renderizar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ConfirmProvider>
          <MerchantsTab />
        </ConfirmProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  recebidos.length = 0;
  mockRole.mockReturnValue({ canWrite: true, isAdmin: false, isOwner: false, role: 'member', isLoading: false });
  const guarda = async (metodo: string, request: Request) => {
    recebidos.push({ metodo, url: new URL(request.url).pathname, corpo: await request.json().catch(() => null) });
  };
  server.use(
    http.get(`${API}/workspaces/7/merchants`, () => HttpResponse.json(LISTA)),
    http.get(`${API}/workspaces/7/categories`, () => HttpResponse.json([{ id: 5, name: 'Lanche' }, { id: 6, name: 'Mercado' }])),
    http.post(`${API}/workspaces/7/merchants`, async ({ request }) => {
      await guarda('POST', request);
      return HttpResponse.json({ id: 3, name: 'Padaria', aliases: ['padaria pq'], default_category_id: null, transaction_count: 0 });
    }),
    http.post(`${API}/workspaces/7/merchants/:id/merge`, async ({ request }) => {
      await guarda('POST', request);
      return HttpResponse.json(LISTA[0]);
    }),
    http.put(`${API}/workspaces/7/merchants/:id`, async ({ request }) => {
      await guarda('PUT', request);
      return HttpResponse.json(LISTA[0]);
    }),
  );
});

describe('MerchantsTab', () => {
  it('lista com apelidos, categoria padrão e o link para os lançamentos', async () => {
    renderizar();
    const linha = (await screen.findByText("McDonald's")).closest('li')!;
    expect(within(linha).getByText('ifd mc donalds')).toBeInTheDocument();
    expect(await within(linha).findByText(/categoria padrão Lanche/)).toBeInTheDocument();
    expect(within(linha).getByRole('link', { name: '3 lançamentos' })).toHaveAttribute('href', '/w/7/transactions?estabelecimento=1');
  });

  it('cria com os apelidos separados por vírgula', async () => {
    renderizar();
    await screen.findByText("McDonald's");
    fireEvent.change(screen.getByLabelText('Nome'), { target: { value: ' Padaria ' } });
    fireEvent.change(screen.getByLabelText('Apelidos no extrato (opcional)'), { target: { value: 'PADARIA PQ 01, padaria pq' } });
    fireEvent.click(screen.getByRole('button', { name: /Criar/ }));
    await waitFor(() => expect(recebidos).toHaveLength(1));
    expect(recebidos[0]).toEqual({
      metodo: 'POST', url: '/api/v1/workspaces/7/merchants', corpo: { name: 'Padaria', aliases: ['PADARIA PQ 01', 'padaria pq'] },
    });
  });

  it('mescla no escolhido só depois do "sim"', async () => {
    renderizar();
    const linha = (await screen.findByText('MC DONALDS')).closest('li')!;
    fireEvent.click(within(linha).getByRole('button', { name: /Mesclar/ }));
    fireEvent.change(within(linha).getByLabelText('É o mesmo que'), { target: { value: '1' } });
    fireEvent.click(within(linha).getByRole('button', { name: 'Mesclar' }));
    const dialogo = await screen.findByRole('dialog');
    expect(dialogo).toHaveTextContent(/o lançamento dele passa para "McDonald's"/);
    expect(recebidos).toEqual([]);
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Mesclar' }));
    await waitFor(() => expect(recebidos).toHaveLength(1));
    expect(recebidos[0]).toEqual({ metodo: 'POST', url: '/api/v1/workspaces/7/merchants/2/merge', corpo: { into_id: 1 } });
  });

  it('editar tira a categoria padrão com null', async () => {
    renderizar();
    const linha = (await screen.findByText("McDonald's")).closest('li')!;
    await within(linha).findByText(/categoria padrão Lanche/);
    fireEvent.click(within(linha).getByRole('button', { name: /Editar/ }));
    const edicao = screen.getByLabelText('Categoria padrão').closest('li')!;
    fireEvent.change(within(edicao).getByLabelText('Categoria padrão'), { target: { value: '' } });
    fireEvent.click(within(edicao).getByRole('button', { name: 'Salvar' }));
    await waitFor(() => expect(recebidos).toHaveLength(1));
    expect(recebidos[0].corpo).toEqual({ name: "McDonald's", aliases: ['ifd mc donalds'], default_category_id: null });
  });

  it('quem só lê não vê criar, editar, mesclar nem excluir', async () => {
    mockRole.mockReturnValue({ canWrite: false, isAdmin: false, isOwner: false, role: 'viewer', isLoading: false });
    renderizar();
    await screen.findByText("McDonald's");
    expect(screen.queryByRole('button', { name: /Criar/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Editar/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Mesclar/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Excluir/ })).not.toBeInTheDocument();
  });
});
