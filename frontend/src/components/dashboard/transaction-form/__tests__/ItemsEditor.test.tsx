import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/setup';
import { describe, it, expect, beforeEach } from 'vitest';
import { NewTransactionDialog } from '../../NewTransactionDialog';
import { TransactionForm } from '../TransactionForm';
import { fromApiTransaction } from '../schema';
import type { TransactionRead } from '@/types/transaction';
import { useAuthStore, useUIStore } from '@/stores';
import { ConfirmProvider } from '@/components/ui/confirm';

const WS = 'http://localhost:8000/api/v1/workspaces/1';

const members = [
  { user_id: 1, role: 'owner', user_name: 'Alice', user_email: 'alice@t.com', joined_at: '2026-01-01' },
  { user_id: 2, role: 'member', user_name: 'Bob', user_email: 'bob@t.com', joined_at: '2026-01-01' },
];

function renderForm() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const resultado = render(
    <QueryClientProvider client={queryClient}>
    {/* `ConfirmProvider`: o diálogo passou a PERGUNTAR antes de descartar um
        formulário preenchido (Escape ou clique fora jogavam fora título, valor,
        pagadores, divisão e anexos sem aviso). `useConfirm` lança sem o
        provider, exatamente como já acontecia no teste da Administração. */}
      <ConfirmProvider>
        <NewTransactionDialog open onOpenChange={() => {}} />
      </ConfirmProvider>
    </QueryClientProvider>
  );
  /*
   * O diálogo de CRIAÇÃO abre no modo simples — título, valor e salvar. Tudo o
   * que este arquivo exercita (pagadores, itens, divisão, anexos) mora atrás de
   * "Detalhar", que é o ponto da mudança: o formulário deixou de abrir com doze
   * controles para preencher dois campos.
   *
   * O clique fica no helper, e não em cada teste, porque ele não é o assunto de
   * nenhum deles: é a porta de entrada do formulário completo.
   */
  fireEvent.click(screen.getByRole('button', { name: /^Detalhar$/i }));
  return resultado;
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
    // A divisão por item mora em "Dividir por valor, porcentagem ou por item"
    fireEvent.click(screen.getByRole('button', { name: /Dividir por valor, porcentagem ou por item/i }));
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

  /*
   * Os itens passaram a atravessar a troca de modo (a nota não muda porque mudou
   * quem divide). A linha que "Por item" semeia em branco não pode ir junto:
   * quem só olhou a opção e voltou teria um formulário reprovado por um item que
   * ninguém quis.
   */
  it('voltar para "Pela despesa" descarta a linha semeada em branco', async () => {
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

    fireEvent.click(screen.getByRole('radio', { name: 'Pela despesa' }));
    await waitFor(() => expect(screen.queryByTestId('item-row-0')).toBeNull());

    fireEvent.click(screen.getByRole('button', { name: 'Salvar despesa' }));
    await waitFor(() => expect(payload).not.toBeNull());
    expect(payload!.split_mode).toBe('transaction');
    expect(payload!.items).toEqual([]);
    expect(payload!.adjustments).toEqual([]);
  });

  it('a linha preenchida em "Por item" vira nota ao dividir pela despesa', async () => {
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
    fireEvent.change(screen.getByLabelText('Título do item'), { target: { value: 'Carne' } });
    fireEvent.change(screen.getByLabelText('Quantidade'), { target: { value: '3' } });
    fireEvent.change(screen.getByLabelText('Valor unitário'), { target: { value: '30,00' } });

    fireEvent.click(screen.getByRole('radio', { name: 'Pela despesa' }));
    // Continua à vista, agora como nota, e sem a divisão por item.
    expect(await screen.findByText('O que foi comprado. A divisão vale para a despesa inteira.')).toBeInTheDocument();
    expect(screen.queryByText('Dividir este item')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Salvar despesa' }));
    await waitFor(() => expect(payload).not.toBeNull());
    expect(payload!.split_mode).toBe('transaction');
    expect(payload!.items).toEqual([expect.objectContaining({ title: 'Carne', amount: 90, quantity: 3, unit: 'un' })]);
    expect((payload!.items as Record<string, unknown>[])[0]).not.toHaveProperty('shares');
  });

  it('quantidade × unitário calcula o total da linha automaticamente', async () => {
    renderForm();
    await screen.findAllByText('Alice');
    await switchToItemMode();

    fireEvent.change(screen.getByLabelText('Quantidade'), { target: { value: '3' } });
    fireEvent.change(screen.getByLabelText('Valor unitário'), { target: { value: '10,00' } });

    await waitFor(() => {
      const lineTotal = screen.getByLabelText('Total do item') as HTMLInputElement;
      expect(lineTotal.value).toBe('30,00');
    });
  });

  it('a linha da nota aceita peso e preço com 3 casas, e a conta não é de ponto flutuante', async () => {
    renderForm();
    await screen.findAllByText('Alice');
    await switchToItemMode();

    // 2,050 kg × R$ 19,90 = 40,795 → R$ 40,80. A conta antiga, em float, dava
    // 4079,4999… centavos e mostrava R$ 40,79, que o servidor recusava.
    fireEvent.change(screen.getByLabelText('Unidade'), { target: { value: 'kg' } });
    fireEvent.change(screen.getByLabelText('Quantidade'), { target: { value: '2,050' } });
    fireEvent.change(screen.getByLabelText('Valor unitário'), { target: { value: '19,90' } });
    await waitFor(() => {
      expect((screen.getByLabelText('Total do item') as HTMLInputElement).value).toBe('40,80');
    });

    // O litro com 3 casas: o MoneyInput leria "5899" como R$ 58,99.
    fireEvent.change(screen.getByLabelText('Quantidade'), { target: { value: '40,123' } });
    fireEvent.change(screen.getByLabelText('Valor unitário'), { target: { value: '5,899' } });
    await waitFor(() => {
      expect((screen.getByLabelText('Total do item') as HTMLInputElement).value).toBe('236,69');
    });

    // Quinta casa no preço, quarta na quantidade: a tecla é ignorada.
    const unitario = screen.getByLabelText('Valor unitário') as HTMLInputElement;
    fireEvent.change(unitario, { target: { value: '5,89901' } });
    expect(unitario.value).toBe('5,899');
    const quantidade = screen.getByLabelText('Quantidade') as HTMLInputElement;
    fireEvent.change(quantidade, { target: { value: '40,1234' } });
    expect(quantidade.value).toBe('40,123');
  });

  it('item novo sem preço unitário não salva e diz o que falta', async () => {
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
    fireEvent.change(screen.getByLabelText('Total do item'), { target: { value: '90,00' } });
    fireEvent.click(screen.getByRole('button', { name: 'Salvar despesa' }));

    await screen.findByText('Informe o preço unitário da nota');
    expect(createCalled).toBe(false);
  });

  it('o total da nota pode diferir da conta em 1 centavo, e mais que isso é recusado', async () => {
    renderForm();
    await screen.findAllByText('Alice');
    await switchToItemMode();
    fireEvent.change(screen.getByLabelText('Valor Total'), { target: { value: '49,27' } });

    fireEvent.change(screen.getByLabelText('Título do item'), { target: { value: 'Picanha' } });
    fireEvent.change(screen.getByLabelText('Unidade'), { target: { value: 'kg' } });
    fireEvent.change(screen.getByLabelText('Quantidade'), { target: { value: '1,235' } });
    fireEvent.change(screen.getByLabelText('Valor unitário'), { target: { value: '39,90' } });
    await waitFor(() => {
      expect((screen.getByLabelText('Total do item') as HTMLInputElement).value).toBe('49,28');
    });

    // A balança truncou: a nota diz R$ 49,27. A pessoa corrige o total e vale.
    fireEvent.change(screen.getByLabelText('Total do item'), { target: { value: '49,27' } });
    await waitFor(() => {
      expect(screen.getByTestId('items-summary').textContent).toContain('Itens fecham');
    });
    expect(screen.queryByText(/confira a nota/)).toBeNull();

    // R$ 49,40 é leitura errada.
    fireEvent.change(screen.getByLabelText('Total do item'), { target: { value: '49,40' } });
    expect(await screen.findByText(/1,235 kg × unitário dá R\$\s49,28 — confira a nota/)).toBeInTheDocument();
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

    fireEvent.click(screen.getByRole('button', { name: 'Salvar despesa' }));

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

    // Item 1: Carne, 1,5 kg × R$ 40,00 = 60, dividida igual entre Alice e Bob
    fireEvent.change(screen.getByLabelText('Título do item'), { target: { value: 'Carne' } });
    fireEvent.change(screen.getByLabelText('Unidade'), { target: { value: 'kg' } });
    fireEvent.change(screen.getByLabelText('Quantidade'), { target: { value: '1,5' } });
    fireEvent.change(screen.getByLabelText('Valor unitário'), { target: { value: '40,00' } });
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

    fireEvent.click(screen.getByRole('button', { name: 'Salvar despesa' }));

    await waitFor(() => expect(payload).not.toBeNull());
    expect(payload!.split_mode).toBe('item');
    expect(payload!.splits).toEqual([]);
    expect(payload!.items).toEqual([
      {
        title: 'Carne', description: null, amount: 60, quantity: 1.5, unit: 'kg', unit_amount: 40, position: 0, category_id: null,
        shares: [
          { user_id: 1, split_method: 'equal', input_value: 0 },
          { user_id: 2, split_method: 'equal', input_value: 0 },
        ],
      },
      {
        title: 'Cerveja', description: null, amount: 30, quantity: 3, unit: 'un', unit_amount: 10, position: 1, category_id: null,
        shares: [{ user_id: 2, split_method: 'equal', input_value: 0 }],
      },
    ]);
  });
});

describe('TransactionForm — editar uma nota já lançada', () => {
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

  type ItemLido = NonNullable<TransactionRead['items']>[number];
  const nota = (item: Partial<ItemLido> = {}): TransactionRead => ({
    id: 9, workspace_id: 1, title: 'Açougue', total_amount: '49.27', currency: 'BRL',
    transaction_date: '2026-09-20T15:00:00Z', billing_month: '2026-09', status: 'confirmed',
    split_mode: 'item', payment_method: 'pix', credit_card_id: null, created_by: 1,
    created_at: '', updated_at: '', tags: [], adjustments: [],
    payers: [{ id: 1, user_id: 1, amount: '49.27' }],
    splits: [],
    items: [{
      id: 1, title: 'Picanha', amount: '49.27', quantity: '1.235', unit: 'kg', unit_amount: '39.9000',
      position: 0, category_id: null,
      shares: [{ id: 1, user_id: 1, split_method: 'equal', input_value: '0.00', computed_amount: '49.27' }],
      ...item,
    }],
  } as TransactionRead);

  function renderEdicao(tx: TransactionRead, onSubmit: (p: unknown) => Promise<void>) {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <ConfirmProvider>
          <TransactionForm initialValues={fromApiTransaction(tx)} onSubmit={onSubmit} submitLabel="Salvar Alterações" />
        </ConfirmProvider>
      </QueryClientProvider>
    );
  }

  it('abrir não recalcula o total que a balança imprimiu', async () => {
    // 1,235 × 39,90 = 49,2765. A nota truncada diz R$ 49,27; recalcular na
    // montagem trocaria a verdade pela conta, e salvar gravaria R$ 49,28.
    let enviado: { items: Record<string, unknown>[] } | null = null;
    renderEdicao(nota(), async (p) => { enviado = p as typeof enviado; });

    expect(((await screen.findByLabelText('Total do item')) as HTMLInputElement).value).toBe('49,27');
    expect((screen.getByLabelText('Quantidade') as HTMLInputElement).value).toBe('1,235');
    expect((screen.getByLabelText('Valor unitário') as HTMLInputElement).value).toBe('39,90');
    expect((screen.getByLabelText('Unidade') as HTMLSelectElement).value).toBe('kg');

    fireEvent.click(screen.getByRole('button', { name: 'Salvar Alterações' }));
    await waitFor(() => expect(enviado).not.toBeNull());
    expect(enviado!.items[0]).toMatchObject({ amount: 49.27, quantity: 1.235, unit: 'kg', unit_amount: 39.9 });
  });

  it('linha antiga sem medida salva sem pedir uma', async () => {
    let enviado: { items: Record<string, unknown>[] } | null = null;
    renderEdicao(
      nota({ quantity: '1.000', unit: null, unit_amount: null }),
      async (p) => { enviado = p as typeof enviado; },
    );

    expect(((await screen.findByLabelText('Unidade')) as HTMLSelectElement).value).toBe('');
    expect(screen.getByText('(opcional)')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Salvar Alterações' }));
    await waitFor(() => expect(enviado).not.toBeNull());
    expect(enviado!.items[0]).toMatchObject({ unit: null, unit_amount: null });
  });
});

describe('TransactionForm — a nota da despesa dividida pelo total', () => {
  beforeEach(() => {
    useAuthStore.getState().setUser({ id: 1, name: 'Alice', email: 'alice@t.com' });
    useUIStore.getState().setCurrentWorkspaceId(1);
    server.use(
      http.get(`${WS}/members`, () => HttpResponse.json(members)),
      http.get(`${WS}/invites`, () => HttpResponse.json([])),
      http.get(`${WS}/categories`, () => HttpResponse.json([{ id: 1, name: 'Alimentação' }])),
      http.get(`${WS}/credit-cards/`, () => HttpResponse.json([])),
      http.get(`${WS}/tags`, () => HttpResponse.json([])),
    );
  });

  // O lançamento #302 como a IA o gravou: um item com medida, três ajustes, e a
  // despesa dividida pelo total. A edição abria sem nada disso.
  const delivery = {
    id: 302, workspace_id: 1, title: "McDonald's", total_amount: '37.41', currency: 'BRL',
    transaction_date: '2026-09-27T15:00:00Z', billing_month: '2026-09', status: 'confirmed',
    split_mode: 'transaction', payment_method: 'pix', credit_card_id: null,
    created_at: '', updated_at: '', tags: [],
    payers: [{ id: 1, user_id: 1, amount: '37.41' }],
    splits: [{ id: 1, user_id: 1, split_method: 'equal', input_value: '0.00', computed_amount: '37.41' }],
    items: [{
      id: 7, title: 'Combo: Big Mac + Quarterão', description: 'Combo com 2 sanduíches.',
      amount: '37.90', quantity: '1.000', unit: 'un', unit_amount: '37.9000', position: 0, category_id: 1, shares: [],
    }],
    adjustments: [
      { id: 1, type: 'discount', amount: '-9.47', description: 'Desconto do pedido' },
      { id: 2, type: 'shipping', amount: '7.99', description: 'Taxa de entrega' },
      { id: 3, type: 'other', amount: '0.99', description: 'Taxa de serviço' },
    ],
  } as unknown as TransactionRead;

  it('mostra os itens e os ajustes, e salvar os devolve', async () => {
    let enviado: { items: Record<string, unknown>[]; adjustments: Record<string, unknown>[] } | null = null;
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <ConfirmProvider>
          <TransactionForm
            initialValues={fromApiTransaction(delivery)}
            onSubmit={async (p) => { enviado = p as unknown as typeof enviado; }}
            submitLabel="Salvar Alterações"
          />
        </ConfirmProvider>
      </QueryClientProvider>
    );

    // A nota aparece sem abrir "Dividir por…": ela diz o que foi comprado.
    expect(await screen.findByText('Itens da nota')).toBeInTheDocument();
    expect((screen.getByLabelText('Título do item') as HTMLInputElement).value).toBe('Combo: Big Mac + Quarterão');
    expect((screen.getByLabelText('Total do item') as HTMLInputElement).value).toBe('37,90');
    expect(screen.getByText('Combo com 2 sanduíches.')).toBeInTheDocument();
    // Sem divisão por item aqui: quem divide é a despesa.
    expect(screen.queryByText('Dividir este item')).toBeNull();

    const tipos = screen.getAllByLabelText('Tipo do ajuste') as HTMLSelectElement[];
    expect(tipos.map((t) => t.value)).toEqual(['discount', 'shipping', 'other']);
    expect((screen.getAllByLabelText('Valor do ajuste') as HTMLInputElement[]).map((i) => i.value))
      .toEqual(['9,47', '7,99', '0,99']);
    expect(screen.getByTestId('items-summary').textContent).toMatch(/fecham R\$\s37,41/);

    fireEvent.click(screen.getByRole('button', { name: 'Salvar Alterações' }));
    await waitFor(() => expect(enviado).not.toBeNull());
    expect(enviado!.items).toEqual([expect.objectContaining({
      title: 'Combo: Big Mac + Quarterão', description: 'Combo com 2 sanduíches.', amount: 37.9, unit: 'un', category_id: 1,
    })]);
    expect(enviado!.adjustments).toEqual([
      { type: 'discount', description: 'Desconto do pedido', amount: -9.47 },
      { type: 'shipping', description: 'Taxa de entrega', amount: 7.99 },
      { type: 'other', description: 'Taxa de serviço', amount: 0.99 },
    ]);
  });
});
