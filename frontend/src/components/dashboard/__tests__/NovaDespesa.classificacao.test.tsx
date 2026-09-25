import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/setup';
import { describe, it, expect, beforeEach } from 'vitest';
import { NewTransactionDialog } from '../NewTransactionDialog';
import { useAuthStore, useUIStore } from '@/stores';
import { ConfirmProvider } from '@/components/ui/confirm';

/**
 * Categoria, tags, observação e a divisão detalhada no formulário da despesa.
 *
 * A categoria (a que os relatórios e as metas usam) morava em "Opções
 * avançadas", dois cliques abaixo, e passava por "a outra tag" que ninguém
 * achava. A observação existia no lançamento, mas não tinha campo. E a divisão
 * por valor, porcentagem ou item ficava atrás de um nome genérico.
 */
const WS = 'http://localhost:8000/api/v1/workspaces/1';

function renderForm() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ConfirmProvider>
        <NewTransactionDialog open onOpenChange={() => {}} />
      </ConfirmProvider>
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole('button', { name: /^Detalhar$/i }));
}

describe('Nova despesa — categoria, tags, observação e divisão', () => {
  beforeEach(() => {
    useAuthStore.getState().setUser({ id: 1, name: 'Alice', email: 'alice@t.com' });
    useUIStore.getState().setCurrentWorkspaceId(1);
    server.use(
      http.get(`${WS}/members`, () => HttpResponse.json([
        { user_id: 1, role: 'owner', user_name: 'Alice', user_email: 'alice@t.com', joined_at: '2026-01-01' },
      ])),
      http.get(`${WS}/invites`, () => HttpResponse.json([])),
      http.get(`${WS}/categories`, () => HttpResponse.json([{ id: 7, name: 'Mercado' }])),
      http.get(`${WS}/tags`, () => HttpResponse.json([])),
    );
  });

  it('categoria e observação aparecem ao detalhar, sem abrir a divisão, e cada campo diz o que é', async () => {
    renderForm();
    expect(await screen.findByRole('option', { name: 'Mercado' })).toBeInTheDocument();
    expect(screen.getByLabelText('Categoria')).toBeInTheDocument();
    expect(screen.getByText(/entra nos relatórios e nas metas/)).toBeInTheDocument();
    expect(screen.getByText(/Não entram nas metas/)).toBeInTheDocument();
    expect(screen.getByLabelText('Observação')).toBeInTheDocument();
    expect(screen.queryByRole('radio', { name: 'Por item' })).not.toBeInTheDocument();
  });

  it('envia a observação e a categoria escolhidas', async () => {
    let payload: Record<string, unknown> | null = null;
    server.use(
      http.post(`${WS}/transactions/`, async ({ request }) => {
        payload = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: 1, ...payload });
      }),
    );
    renderForm();
    await screen.findByRole('option', { name: 'Mercado' });
    fireEvent.change(screen.getByLabelText('Título / Descrição'), { target: { value: 'Feira' } });
    fireEvent.change(screen.getByLabelText('Valor Total'), { target: { value: '90,00' } });
    fireEvent.change(screen.getByLabelText('Categoria'), { target: { value: '7' } });
    fireEvent.change(screen.getByLabelText('Observação'), { target: { value: '  Verduras da semana  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Salvar despesa' }));

    await waitFor(() => expect(payload).not.toBeNull());
    expect(payload!.description).toBe('Verduras da semana');
    expect(payload!.items).toEqual([expect.objectContaining({ category_id: 7 })]);
  });

  it('a divisão detalhada tem nome próprio, e na divisão por item a categoria vai em cada item', async () => {
    renderForm();
    await screen.findByRole('option', { name: 'Mercado' });
    fireEvent.click(screen.getByRole('button', { name: 'Dividir por valor, porcentagem ou por item' }));
    expect(screen.getByRole('button', { name: 'Voltar à divisão em partes iguais' })).toHaveAttribute('aria-expanded', 'true');
    fireEvent.click(screen.getByRole('radio', { name: 'Por item' }));
    expect(screen.getByText('Na divisão por item, cada item tem a sua categoria.')).toBeInTheDocument();
  });
});
