import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/setup';
import { ConfirmProvider } from '@/components/ui/confirm';
import { TagsCard } from '../TagsCard';

/**
 * Tags em Configurações (ao lado das categorias). Até aqui a tag só existia no
 * lançamento: não havia onde renomear nem apagar uma que sobrou.
 */
const API = 'http://localhost:8000/api/v1';
const mockRole = vi.hoisted(() => vi.fn(() => ({ canWrite: true, isAdmin: false, isOwner: false, role: 'member', isLoading: false })));
vi.mock('@/hooks/use-workspace-role', () => ({ useWorkspaceRole: () => mockRole() }));
vi.mock('@/hooks/use-workspace-id', () => ({ useWorkspaceId: () => 7 }));

const recebidos: Array<{ metodo: string; url: string; corpo: unknown }> = [];

function renderizar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ConfirmProvider>
        <TagsCard />
      </ConfirmProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  recebidos.length = 0;
  mockRole.mockReturnValue({ canWrite: true, isAdmin: false, isOwner: false, role: 'member', isLoading: false });
  server.use(
    http.get(`${API}/workspaces/7/tags`, () => HttpResponse.json([{ id: 1, name: 'viagem' }, { id: 2, name: 'presente' }])),
    http.put(`${API}/workspaces/7/tags/:id`, async ({ request }) => {
      recebidos.push({ metodo: 'PUT', url: new URL(request.url).pathname, corpo: await request.json() });
      return HttpResponse.json({ id: 1, name: 'viagens' });
    }),
    http.delete(`${API}/workspaces/7/tags/:id`, ({ request }) => {
      recebidos.push({ metodo: 'DELETE', url: new URL(request.url).pathname, corpo: null });
      return HttpResponse.json({ status: 'ok' });
    }),
  );
});

describe('TagsCard', () => {
  it('diz que tag não é categoria e renomeia', async () => {
    renderizar();
    expect(screen.getByText(/não entram nas metas/)).toBeInTheDocument();
    await screen.findByText('#viagem');
    fireEvent.click(screen.getByRole('button', { name: 'Renomear a tag viagem' }));
    fireEvent.change(screen.getByLabelText('Novo nome da tag viagem'), { target: { value: 'viagens' } });
    fireEvent.click(screen.getByRole('button', { name: 'OK' }));
    await waitFor(() => expect(recebidos).toHaveLength(1));
    expect(recebidos[0]).toEqual({ metodo: 'PUT', url: '/api/v1/workspaces/7/tags/1', corpo: { name: 'viagens' } });
  });

  it('exclui só depois do "sim", avisando que sai dos lançamentos', async () => {
    renderizar();
    await screen.findByText('#presente');
    fireEvent.click(screen.getByRole('button', { name: 'Excluir a tag presente' }));
    const dialogo = await screen.findByRole('dialog');
    expect(dialogo).toHaveTextContent('sai de todos os lançamentos');
    expect(recebidos).toEqual([]);
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Excluir' }));
    await waitFor(() => expect(recebidos).toEqual([{ metodo: 'DELETE', url: '/api/v1/workspaces/7/tags/2', corpo: null }]));
  });

  it('quem só lê vê as tags, sem criar, renomear nem excluir', async () => {
    mockRole.mockReturnValue({ canWrite: false, isAdmin: false, isOwner: false, role: 'viewer', isLoading: false });
    renderizar();
    await screen.findByText('#viagem');
    expect(screen.queryByLabelText('Nova tag')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Renomear/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Excluir/ })).not.toBeInTheDocument();
  });
});
