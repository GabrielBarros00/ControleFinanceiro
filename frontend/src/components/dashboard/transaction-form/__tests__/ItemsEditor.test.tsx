import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/setup';
import { describe, it, expect, beforeEach } from 'vitest';
import { SplitEntryForm } from '../../SplitEntryForm';
import { useAuthStore, useUIStore } from '@/stores';

const WS = 'http://localhost:8000/api/v1/workspaces/1';

const members = [
  { user_id: 1, role: 'owner', user_name: 'Alice', user_email: 'alice@t.com', joined_at: '2026-01-01' },
  { user_id: 2, role: 'member', user_name: 'Bob', user_email: 'bob@t.com', joined_at: '2026-01-01' },
];

function renderForm() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <SplitEntryForm />
    </QueryClientProvider>
  );
}

describe('TransactionForm — divisão por item', () => {
  beforeEach(() => {
    useAuthStore.getState().setUser({ id: 1, name: 'Alice', email: 'alice@t.com' });
    useUIStore.getState().setCurrentWorkspaceId(1);
    server.use(
      http.get(`${WS}/members`, () => HttpResponse.json(members)),
      http.get(`${WS}/invites`, () => HttpResponse.json([])),
      http.get(`${WS}/categories`, () => HttpResponse.json([])),
      http.get(`${WS}/credit-cards/`, () => HttpResponse.json([])),
      http.get(`${WS}/tags`, () => HttpResponse.json([])),
    );
  });

  async function switchToItemMode() {
    fireEvent.change(screen.getByLabelText('Título / Descrição'), { target: { value: 'Churrasco' } });
    fireEvent.change(screen.getByLabelText('Valor Total'), { target: { value: '90,00' } });
    fireEvent.click(screen.getByRole('radio', { name: 'Por item' }));
    await waitFor(() => {
      expect(screen.getByTestId('item-row-0')).toBeInTheDocument();
    });
  }

  it('alternar para "Por item" abre o editor com um item semeado', async () => {
    renderForm();
    await screen.findAllByText('Alice');
    await switchToItemMode();

    expect(screen.getAllByLabelText('Título do item')).toHaveLength(1);
    // participante default: usuário logado
    const share = screen.getByLabelText('Participante do item 1') as HTMLSelectElement;
    expect(share.value).toBe('1');
  });

  it('quantidade × unitário calcula o total da linha automaticamente', async () => {
    renderForm();
    await screen.findAllByText('Alice');
    await switchToItemMode();

    fireEvent.change(screen.getByLabelText('Quantidade'), { target: { value: '3' } });
    fireEvent.change(screen.getByLabelText('Valor unitário'), { target: { value: '10,00' } });

    await waitFor(() => {
      const lineTotal = screen.getByLabelText('Total do item');
      expect(lineTotal.textContent).toContain('30,00');
    });
  });

  it('bloqueia submit quando itens não fecham o total e mostra o que falta', async () => {
    let createCalled = false;
    server.use(
      http.post(`${WS}/transactions/`, () => {
        createCalled = true;
        return HttpResponse.json({ id: 1 });
      })
    );
    renderForm();
    await screen.findAllByText('Alice');
    await switchToItemMode();

    fireEvent.change(screen.getByLabelText('Título do item'), { target: { value: 'Carne' } });
    fireEvent.change(screen.getByLabelText('Total do item'), { target: { value: '60,00' } });

    fireEvent.click(screen.getByRole('button', { name: 'Salvar Despesa' }));

    await screen.findAllByText(/faltam R\$\s*30,00/);
    expect(createCalled).toBe(false);
  });

  it('envia payload de modo item com shares por item e splits vazios', async () => {
    let payload: Record<string, unknown> | null = null;
    server.use(
      http.post(`${WS}/transactions/`, async ({ request }) => {
        payload = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: 1, ...payload });
      })
    );
    renderForm();
    await screen.findAllByText('Alice');
    await switchToItemMode();

    // Item 1: Carne 60, dividido igual entre Alice e Bob
    fireEvent.change(screen.getByLabelText('Título do item'), { target: { value: 'Carne' } });
    fireEvent.change(screen.getByLabelText('Total do item'), { target: { value: '60,00' } });
    fireEvent.click(screen.getAllByRole('button', { name: '+ Participante' })[0]);
    await waitFor(() => {
      expect(screen.getAllByLabelText('Participante do item 1')).toHaveLength(2);
    });
    fireEvent.change(screen.getAllByLabelText('Participante do item 1')[1], { target: { value: '2' } });

    // Item 2: Cerveja 3 × 10 só do Bob
    fireEvent.click(screen.getByRole('button', { name: 'Item' }));
    await waitFor(() => {
      expect(screen.getByTestId('item-row-1')).toBeInTheDocument();
    });
    fireEvent.change(screen.getAllByLabelText('Título do item')[1], { target: { value: 'Cerveja' } });
    fireEvent.change(screen.getAllByLabelText('Quantidade')[1], { target: { value: '3' } });
    fireEvent.change(screen.getAllByLabelText('Valor unitário')[1], { target: { value: '10,00' } });
    fireEvent.change(screen.getByLabelText('Participante do item 2'), { target: { value: '2' } });

    fireEvent.click(screen.getByRole('button', { name: 'Salvar Despesa' }));

    await waitFor(() => expect(payload).not.toBeNull());
    expect(payload!.split_mode).toBe('item');
    expect(payload!.splits).toEqual([]);
    expect(payload!.items).toEqual([
      {
        title: 'Carne', amount: 60, quantity: 1, unit_amount: null, position: 0, category_id: null,
        shares: [
          { user_id: 1, split_method: 'equal', input_value: 0 },
          { user_id: 2, split_method: 'equal', input_value: 0 },
        ],
      },
      {
        title: 'Cerveja', amount: 30, quantity: 3, unit_amount: 10, position: 1, category_id: null,
        shares: [{ user_id: 2, split_method: 'equal', input_value: 0 }],
      },
    ]);
  });
});
