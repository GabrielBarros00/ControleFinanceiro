import { describe, expect, it } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { apiClient } from '@/api/client';
import { server } from '@/test/setup';
import { WorkspaceGuard } from '@/components/layout/WorkspaceGuard';
import { InviteAcceptPage } from '../InviteAcceptPage';

const API = 'http://localhost:8000/api/v1';

describe('aceitar convite com a lista de espaços em cache', () => {
  it.each(['consulta inativa', 'bootstrap sem queryFn'])('atualiza a participação com %s e rede lenta antes de entrar no espaço', async (origem) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } });
    // A tela de convite fica fora do layout: esta consulta existe, mas está inativa.
    if (origem === 'bootstrap sem queryFn') {
      // useAuth semeia a lista antes que useWorkspaces tenha sido montado.
      client.setQueryData(['workspaces'], [{ id: 1, name: 'Main Workspace' }]);
    } else {
      await client.fetchQuery({
        queryKey: ['workspaces'],
        queryFn: async () => (await apiClient.get('/workspaces/')).data,
      });
    }
    let liberar!: () => void;
    const resposta = new Promise<void>((resolve) => { liberar = resolve; });
    let consultou = false;
    server.use(
      http.get(`${API}/invites/info/token`, () => HttpResponse.json({ workspace_name: 'Casa', valid: true })),
      http.post(`${API}/invites/accept/token`, () => HttpResponse.json({ workspace_id: 7 })),
      http.get(`${API}/workspaces/`, async () => {
        consultou = true;
        await resposta;
        return HttpResponse.json([{ id: 1, name: 'Main Workspace' }, { id: 7, name: 'Casa' }]);
      }),
    );
    const tela = render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/invite/token']}>
          <Routes>
            <Route path="/invite/:token" element={<InviteAcceptPage />} />
            <Route path="/w/:workspaceId" element={<WorkspaceGuard />}>
              <Route index element={<p>Espaço aceito aberto</p>} />
            </Route>
            <Route path="/overview" element={<p>Redirecionamento indevido</p>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    try {
      await screen.findByText(/Casa/);
      const aceitar = screen.getByRole('button', { name: 'Aceitar Convite' });
      fireEvent.click(aceitar);
      await waitFor(() => expect(consultou).toBe(true));
      expect(screen.queryByText('Redirecionamento indevido')).not.toBeInTheDocument();
      expect(aceitar).toBeDisabled();
      await act(async () => { liberar(); });
      expect(await screen.findByText('Espaço aceito aberto')).toBeInTheDocument();
      expect(screen.queryByText('Redirecionamento indevido')).not.toBeInTheDocument();
    } finally {
      liberar();
      tela.unmount();
      client.clear();
    }
  });
});
