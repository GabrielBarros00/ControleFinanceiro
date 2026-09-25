import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/setup';
import { ConfirmProvider } from '@/components/ui/confirm';
import { useUIStore } from '@/stores';
import { ImportHistory } from '../ImportHistory';

/**
 * "Importações anteriores" com Desfazer (ADR 0036). O que não pode errar: só
 * oferecer desfazer quando ainda há o que excluir, perguntar antes (e dizer
 * quantos recibos somem), e só mandar `confirm_attachments` quando há anexo.
 */
const API = 'http://localhost:8000/api/v1/workspaces/1';

const lote = (extra: Record<string, unknown> = {}) => ({
  id: 4, filename: 'extrato-setembro.csv', created_at: '2026-09-22T12:00:00', total_rows: 48,
  imported: 41, ignored: 3, duplicate: 4, skipped: 0, live_transactions: 41, attachments: 0, ...extra,
});

function renderizar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ConfirmProvider>
          <ImportHistory />
        </ConfirmProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ImportHistory', () => {
  beforeEach(() => {
    useUIStore.getState().setCurrentWorkspaceId(1);
  });

  it('lista as importações; a desfeita não oferece desfazer', async () => {
    server.use(http.get(`${API}/imports`, () => HttpResponse.json([
      lote(), lote({ id: 3, filename: 'agosto.csv', imported: 28, live_transactions: 0, duplicate: 2, ignored: 0 }),
    ])));
    renderizar();
    expect(await screen.findByText('extrato-setembro.csv')).toBeInTheDocument();
    expect(screen.getByText(/41 importados · 4 duplicatas · 3 ignorados/)).toBeInTheDocument();
    const agosto = screen.getByText('agosto.csv').closest('li')!;
    expect(within(agosto).getByText('Desfeita')).toBeInTheDocument();
    expect(within(agosto).queryByRole('button', { name: /Desfazer/ })).not.toBeInTheDocument();
  });

  it('sem importações, não ocupa a tela', async () => {
    server.use(http.get(`${API}/imports`, () => HttpResponse.json([])));
    const { container } = renderizar();
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it('desfazer pergunta antes e só então chama o servidor, sem confirmar anexo que não existe', async () => {
    const corpo = vi.fn();
    server.use(
      http.get(`${API}/imports`, () => HttpResponse.json([lote()])),
      http.post(`${API}/imports/4/undo`, async ({ request }) => {
        corpo(await request.json());
        return HttpResponse.json({ batch_id: 4, deleted: 41, attachments_removed: 0 });
      }),
    );
    renderizar();
    fireEvent.click(await screen.findByRole('button', { name: /Desfazer/ }));
    const dialogo = await screen.findByRole('dialog');
    expect(within(dialogo).getByText(/41 lançamentos criados por ela serão excluídos/)).toBeInTheDocument();
    expect(corpo).not.toHaveBeenCalled();
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Desfazer importação' }));
    await waitFor(() => expect(corpo).toHaveBeenCalledWith({ confirm_attachments: false }));
  });

  it('com anexo, avisa quantos recibos somem e confirma o anexo no pedido', async () => {
    const corpo = vi.fn();
    server.use(
      http.get(`${API}/imports`, () => HttpResponse.json([lote({ attachments: 2 })])),
      http.post(`${API}/imports/4/undo`, async ({ request }) => {
        corpo(await request.json());
        return HttpResponse.json({ batch_id: 4, deleted: 41, attachments_removed: 2 });
      }),
    );
    renderizar();
    fireEvent.click(await screen.findByRole('button', { name: /Desfazer/ }));
    const dialogo = await screen.findByRole('dialog');
    expect(within(dialogo).getByText(/2 recibos anexados serão apagados para sempre/)).toBeInTheDocument();
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Desfazer importação' }));
    await waitFor(() => expect(corpo).toHaveBeenCalledWith({ confirm_attachments: true }));
  });
});
