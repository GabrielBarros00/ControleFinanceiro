/** @jsxImportSource preact */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render } from 'preact';
import { act } from 'preact/test-utils';
import { fireEvent, screen, waitFor, within } from '@testing-library/dom';
import type { Ambiente, Bridge, ToolResultLike } from '../bridge';
import { Widget } from '../Widget';
import { day, money, month, monthLong, percent, plural, shortDay } from '../format';

/**
 * O componente v4 (ADR 0035 §11), com o Preact de verdade (o mesmo do build) e uma
 * ponte falsa no lugar do postMessage do host.
 *
 * O que se trava aqui é o CONTRATO com o servidor: cada botão chama a tool certa,
 * com os argumentos certos (a versão lida, a chave de idempotência, só o campo que
 * mudou), e a tela mostra o que a tool devolveu — inclusive o erro.
 */
type Resposta = (args: Record<string, unknown>) => ToolResultLike;

function ponte(respostas: Record<string, Resposta> = {}) {
  let aoResultado: ((r: ToolResultLike) => void) | null = null;
  let aoTema: ((t: 'light' | 'dark') => void) | null = null;
  let aoEntrada: ((a: Record<string, unknown>) => void) | null = null;
  let aoAmbiente: ((a: Ambiente) => void) | null = null;
  const chamadas: Array<{ name: string; args: Record<string, unknown> }> = [];
  const b = {
    chamadas,
    onResult: (cb: (r: ToolResultLike) => void) => { aoResultado = cb; },
    onTheme: (cb: (t: 'light' | 'dark') => void) => { aoTema = cb; },
    onToolInput: (cb: (a: Record<string, unknown>) => void) => { aoEntrada = cb; },
    onAmbiente: (cb: (a: Ambiente) => void) => { aoAmbiente = cb; },
    callTool: vi.fn(async (name: string, args: Record<string, unknown>) => {
      chamadas.push({ name, args });
      return respostas[name]?.(args) ?? { structuredContent: {} };
    }),
    openLink: vi.fn(),
    requestDisplayMode: vi.fn(async (m: string) => m as 'fullscreen'),
    updateModelContext: vi.fn(async () => {}),
    entregar: (r: ToolResultLike) => act(() => aoResultado?.(r)),
    tema: (t: 'light' | 'dark') => act(() => aoTema?.(t)),
    entrada: (a: Record<string, unknown>) => act(() => aoEntrada?.(a)),
    ambiente: (a: Ambiente) => act(() => aoAmbiente?.(a)),
  };
  return b satisfies Bridge;
}

let raiz: HTMLElement;
function monta(b: Bridge) {
  raiz = document.createElement('div');
  document.body.appendChild(raiz);
  act(() => render(<Widget bridge={b} />, raiz));
  return raiz;
}

afterEach(() => {
  if (raiz) {
    render(null, raiz);
    raiz.remove();
  }
  document.documentElement.classList.remove('dark');
});

const clica = async (el: Element) => {
  await act(async () => {
    fireEvent.click(el);
  });
};

const ALICE = { id: 1, name: 'Alice' };
const JOAO = { id: 2, name: 'João' };
const TX = {
  id: 1, title: 'Jantar', amount: '120.01', currency: 'BRL', date: '2026-09-22', status: 'confirmed', settled: true,
  space: { id: 2, name: 'Casa' }, category: { id: 5, name: 'Alimentação' }, my_share: '60.01', tags: [],
  split: [{ person: ALICE, amount: '60.01', is_me: true }, { person: JOAO, amount: '60.00' }],
  version: 'v1', app_url: 'https://app.example/w/2/transactions',
};
const FORM = {
  space_id: 2, categories: [{ id: 5, name: 'Alimentação' }, { id: 6, name: 'Lazer' }], tags: [{ id: 1, name: 'viagem' }],
  cards: [{ id: 9, name: 'Nubank' }], accounts: [{ id: 3, name: 'Itaú', currency: 'BRL' }],
  people: [{ ...ALICE, me: true }, { ...JOAO, me: false }], payment_methods: ['pix', 'cash', 'credit_card'],
};
const resumo = (id: number, title: string, extra: Record<string, unknown> = {}) => ({
  id, title, space: { id: 2, name: 'Casa' }, date: '2026-09-10', amount: '10.00', currency: 'BRL', my_share: '10.00',
  status: 'confirmed', settled: true, category: 'Mercado', ...extra,
});

describe('Widget: chegada do resultado', () => {
  it('enquanto o resultado não chega, mostra a silhueta (sem texto piscando)', () => {
    monta(ponte());
    expect(screen.getByLabelText('Carregando')).toHaveAttribute('aria-busy', 'true');
  });

  it('com a entrada da tool, mostra o que está sendo registrado antes do resultado', () => {
    const b = ponte();
    monta(b);
    b.entrada({ title: 'Mercado', amount: '89.90' });
    expect(screen.getByText('Mercado')).toBeInTheDocument();
    expect(screen.getByText(/89,90/)).toBeInTheDocument();
    expect(screen.getByText('Registrando…')).toBeInTheDocument();
  });

  it('resultado de erro não desenha nada (o texto já está na conversa)', () => {
    const b = ponte();
    const container = monta(b);
    b.entregar({ isError: true, structuredContent: null });
    expect(container).toBeEmptyDOMElement();
  });

  it('um campo inesperado não apaga a tela: vira um aviso', () => {
    const b = ponte();
    monta(b);
    b.entregar({ structuredContent: { card: { id: 1, name: 'Nubank' }, month: '2026-10', purchases: [null] }, _meta: { view: 'statement' } });
    expect(screen.getByRole('status')).toHaveTextContent('Não deu para desenhar esta tela aqui');
  });

  it('segue o tema do host', () => {
    const b = ponte();
    monta(b);
    b.tema('dark');
    expect(document.documentElement.classList.contains('dark')).toBe(true);
    b.tema('light');
    expect(document.documentElement.classList.contains('dark')).toBe(false);
  });

  it('oferece tela cheia só quando o host deixa, e pede o modo pela ponte', async () => {
    const b = ponte();
    monta(b);
    b.entregar({ structuredContent: { transaction: TX }, _meta: { view: 'transaction', mode: 'read' } });
    expect(screen.queryByRole('button', { name: /Tela cheia/ })).not.toBeInTheDocument();
    b.ambiente({ modo: 'inline', modos: ['inline', 'fullscreen'] });
    await clica(screen.getByRole('button', { name: /Tela cheia/ }));
    expect(b.requestDisplayMode).toHaveBeenCalledWith('fullscreen');
    b.ambiente({ modo: 'fullscreen', modos: ['inline', 'fullscreen'] });
    expect(screen.getByRole('button', { name: /Voltar à conversa/ })).toBeInTheDocument();
  });
});

describe('Widget: lançamento', () => {
  it('lido: valor, divisão com a pessoa, sua parte e Abrir no app', async () => {
    const b = ponte();
    monta(b);
    b.entregar({ structuredContent: { transaction: TX }, _meta: { view: 'transaction', mode: 'read', app_url: TX.app_url } });
    expect(screen.getByText('Jantar')).toBeInTheDocument();
    expect(screen.getByText('(você)')).toBeInTheDocument();
    expect(screen.getByText('sua parte')).toBeInTheDocument();
    await clica(screen.getByRole('button', { name: /Abrir no app/ }));
    expect(b.openLink).toHaveBeenCalledWith(TX.app_url);
  });

  it('convertido mostra o valor original', () => {
    const b = ponte();
    monta(b);
    b.entregar({
      structuredContent: { transaction: { ...TX, foreign: { original_amount: '50.00', original_currency: 'USD' } } },
      _meta: { view: 'transaction' },
    });
    expect(screen.getByText(/US\$\s?50,00 convertidos/)).toBeInTheDocument();
  });

  it('itens da nota e a compra inteira aparecem uma vez só', () => {
    const b = ponte();
    monta(b);
    const itens = [
      { title: 'Arroz', quantity: '1', amount: '30.00', shares: [{ person: ALICE, amount: '30.00' }] },
      { title: 'Refrigerante', quantity: '2', unit_amount: '25.00', amount: '50.00', shares: [{ person: ALICE, amount: '25.00' }, { person: JOAO, amount: '25.00' }] },
    ];
    b.entregar({
      structuredContent: {
        transaction: { ...TX, amount: '50.00', installment: { number: 1, of: 2 }, split_mode: 'item',
          purchase: { group_id: 'g', title: 'Mercado', amount: '100.00', currency: 'BRL', installments: 2, paid_installments: 0, my_share: '55.00', items: itens } },
        installments: [resumo(1, 'Mercado', { installment: '1/2', amount: '50.00' }), resumo(2, 'Mercado', { installment: '2/2', amount: '50.00' })],
      },
      _meta: { view: 'transaction', mode: 'read' },
    });
    expect(screen.getByText('Parcela 1/2')).toBeInTheDocument();
    expect(screen.getAllByText('Arroz')).toHaveLength(1);
    expect(screen.getByText(/2 × R\$\s?25,00/)).toBeInTheDocument();
    expect(screen.getByText('0 de 2 pagas')).toBeInTheDocument();
  });

  it('criado: Desfazer chama a exclusão que o servidor mandou no _meta', async () => {
    const b = ponte({ transactions_delete: () => ({ structuredContent: { deleted: [resumo(1, 'Jantar')] } }) });
    monta(b);
    b.entregar({
      structuredContent: { transaction: TX },
      _meta: { view: 'transaction', mode: 'created', undo: { tool: 'transactions_delete', args: { transaction_id: 1, scope: 'installment' } } },
    });
    expect(screen.getByText('Registrado')).toBeInTheDocument();
    await clica(screen.getByRole('button', { name: 'Desfazer' }));
    expect(b.chamadas).toEqual([{ name: 'transactions_delete', args: { transaction_id: 1, scope: 'installment' } }]);
    expect(screen.getByRole('status')).toHaveTextContent('Desfeito: o lançamento foi excluído.');
    expect(b.updateModelContext).toHaveBeenCalledWith(expect.stringContaining('transactions_delete'));
  });

  it('editado pelo assistente: mostra antes → depois de cada campo que mudou', () => {
    const b = ponte();
    monta(b);
    b.entregar({
      structuredContent: { transaction: TX, previous: { ...TX, amount: '100.00', category: { id: 6, name: 'Lazer' } }, changed: ['amount', 'category'] },
      _meta: { view: 'transaction', mode: 'updated' },
    });
    expect(screen.getByText('Atualizado')).toBeInTheDocument();
    const diff = screen.getByText('Valor').closest('li')!;
    expect(within(diff).getByText(/100,00/)).toHaveClass('line-through');
    expect(within(diff).getByText(/120,01/)).toBeInTheDocument();
    expect(screen.getByText('Lazer')).toHaveClass('line-through');
  });

  it('editor: manda só o que mudou, com a versão lida, e mostra a diferença que voltou', async () => {
    const depois = { ...TX, title: 'Jantar fora', version: 'v2' };
    const b = ponte({ transactions_update: () => ({ structuredContent: { transaction: depois, previous: TX, changed: ['title'] } }) });
    monta(b);
    b.entregar({ structuredContent: { transaction: TX }, _meta: { view: 'transaction', mode: 'read', can_edit: true, form: FORM } });
    await clica(screen.getByRole('button', { name: 'Editar' }));
    const titulo = screen.getByLabelText('Título') as HTMLInputElement;
    await act(async () => {
      fireEvent.input(titulo, { target: { value: 'Jantar fora' } });
    });
    await clica(screen.getByRole('button', { name: 'Salvar' }));
    expect(b.chamadas).toEqual([{ name: 'transactions_update', args: { transaction_id: 1, expected_version: 'v1', title: 'Jantar fora' } }]);
    expect(screen.getByText('Atualizado')).toBeInTheDocument();
    expect(screen.getAllByText('Jantar fora').length).toBeGreaterThan(0);
    expect(b.updateModelContext).toHaveBeenCalledWith(expect.stringContaining('#1'));
  });

  it('editor: CONFLICT vira "mudou enquanto você editava", sem fingir que salvou', async () => {
    const b = ponte({
      transactions_update: () => ({
        isError: true,
        content: [{ type: 'text', text: 'Mudou.\n{"error":{"code":"CONFLICT","message":"O lançamento mudou."}}' }],
      }),
    });
    monta(b);
    b.entregar({ structuredContent: { transaction: TX }, _meta: { view: 'transaction', mode: 'read', can_edit: true, form: FORM } });
    await clica(screen.getByRole('button', { name: 'Editar' }));
    await act(async () => {
      fireEvent.input(screen.getByLabelText('Título'), { target: { value: 'Outro' } });
    });
    await clica(screen.getByRole('button', { name: 'Salvar' }));
    expect(screen.getByRole('status')).toHaveTextContent('mudou enquanto você editava');
    expect(screen.queryByText('Atualizado')).not.toBeInTheDocument();
    expect(b.updateModelContext).not.toHaveBeenCalled();
  });

  it('editor sem nada mudado não chama o servidor', async () => {
    const b = ponte();
    monta(b);
    b.entregar({ structuredContent: { transaction: TX }, _meta: { view: 'transaction', mode: 'read', can_edit: true, form: FORM } });
    await clica(screen.getByRole('button', { name: 'Editar' }));
    await clica(screen.getByRole('button', { name: 'Salvar' }));
    expect(b.chamadas).toEqual([]);
  });

  it('sem permissão de escrita (sem form no _meta), não há Editar nem Excluir', () => {
    const b = ponte();
    monta(b);
    b.entregar({ structuredContent: { transaction: TX }, _meta: { view: 'transaction', mode: 'read', can_edit: false } });
    expect(screen.queryByRole('button', { name: 'Editar' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Excluir' })).not.toBeInTheDocument();
  });

  it('excluir pede confirmação no próprio componente e oferece Desfazer depois', async () => {
    const b = ponte({ transactions_delete: () => ({ structuredContent: { deleted: [resumo(1, 'Jantar')] } }) });
    monta(b);
    b.entregar({ structuredContent: { transaction: TX }, _meta: { view: 'transaction', mode: 'read', can_edit: true, form: FORM } });
    await clica(screen.getByRole('button', { name: 'Excluir' }));
    expect(b.chamadas).toEqual([]);
    await clica(screen.getAllByRole('button', { name: 'Excluir' }).at(-1)!);
    expect(b.chamadas[0]).toEqual({ name: 'transactions_delete', args: { transaction_id: 1, scope: 'installment', expected_version: 'v1' } });
    expect(screen.getByText('Excluído')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Desfazer' })).toBeInTheDocument();
  });

  it('excluídos pelo assistente: Desfazer restaura cada um', async () => {
    const b = ponte({ transactions_restore: (a) => ({ structuredContent: { transaction: { ...TX, id: a.transaction_id } } }) });
    monta(b);
    b.entregar({
      structuredContent: { deleted: [resumo(7, 'Cama (1/2)'), resumo(8, 'Cama (2/2)')] },
      _meta: { view: 'transaction', mode: 'deleted', undo: { tool: 'transactions_restore', args: { transaction_id: 7 } },
        undo_each: [{ transaction_id: 7 }, { transaction_id: 8 }] },
    });
    expect(screen.getByText('2 lançamentos excluídos')).toBeInTheDocument();
    await clica(screen.getByRole('button', { name: 'Desfazer exclusão' }));
    expect(b.chamadas.filter((c) => c.name === 'transactions_restore').map((c) => c.args)).toEqual([{ transaction_id: 7 }, { transaction_id: 8 }]);
  });
});

describe('Widget: telas do view_show', () => {
  const lista = (itens: unknown[], cursor: string | null) => ({
    structuredContent: { view: 'transactions', source_tool: 'transactions_search',
      data: { items: itens, next_cursor: cursor, total_count: 3, totals: [{ currency: 'BRL', amount: '30.00', count: 3 }], my_share_totals: [{ currency: 'BRL', amount: '25.00', count: 3 }] } },
    _meta: { view: 'transactions', query: { tool: 'transactions_search', args: { month: '2026-09' } }, forms: { 2: FORM } },
  });

  it('lista: filtros em chips, totais, e "Carregar mais" pelo cursor da própria busca', async () => {
    const b = ponte({ transactions_search: () => ({ structuredContent: { items: [resumo(3, 'Padaria')], next_cursor: null } }) });
    monta(b);
    b.entregar(lista([resumo(1, 'Mercado'), resumo(2, 'Farmácia')], 'c2'));
    expect(screen.getByText('setembro de 2026')).toBeInTheDocument();
    expect(screen.getByText('2 de 3')).toBeInTheDocument();
    await clica(screen.getByRole('button', { name: 'Carregar mais' }));
    expect(b.chamadas).toEqual([{ name: 'transactions_search', args: { month: '2026-09', cursor: 'c2' } }]);
    expect(screen.getByText('Padaria')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Carregar mais' })).not.toBeInTheDocument();
  });

  it('lista: a linha abre o lançamento inteiro sob demanda', async () => {
    const b = ponte({ transactions_get: () => ({ structuredContent: { transaction: TX } }) });
    monta(b);
    b.entregar(lista([resumo(1, 'Jantar')], null));
    expect(b.chamadas).toEqual([]);
    await clica(screen.getByRole('button', { name: /Jantar/ }));
    expect(b.chamadas).toEqual([{ name: 'transactions_get', args: { transaction_id: 1 } }]);
    await waitFor(() => expect(screen.getByText('(você)')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Editar' })).toBeInTheDocument();
  });

  it('lista: selecionar vários pede a prévia de massa com os ids e confirma com o token', async () => {
    const b = ponte({
      transactions_bulk_preview: () => ({ structuredContent: { action: 'settle', count: 2, totals: [], sample: [], confirmation_token: 'cfm_x' } }),
      transactions_bulk_update: () => ({ structuredContent: { action: 'settle', count: 2, transaction_ids: [1, 2] } }),
      transactions_search: () => ({ structuredContent: { items: [], next_cursor: null } }),
    });
    monta(b);
    b.entregar(lista([resumo(1, 'Mercado'), resumo(2, 'Farmácia')], null));
    await clica(screen.getByRole('button', { name: 'Selecionar' }));
    await act(async () => {
      fireEvent.click(screen.getByLabelText('Selecionar Mercado'));
      fireEvent.click(screen.getByLabelText('Selecionar Farmácia'));
    });
    await clica(screen.getByRole('button', { name: 'Marcar pago' }));
    expect(b.chamadas[0]).toEqual({ name: 'transactions_bulk_preview', args: { action: 'settle', transaction_ids: [1, 2] } });
    await clica(screen.getByRole('button', { name: 'Confirmar (2)' }));
    expect(b.chamadas[1]).toEqual({ name: 'transactions_bulk_update', args: { confirmation_token: 'cfm_x' } });
    await waitFor(() => expect(screen.getByText('2 lançamentos marcados como pago.')).toBeInTheDocument());
  });

  it('análise: trocar o agrupamento chama reports_breakdown com os mesmos filtros', async () => {
    const b = ponte({ reports_breakdown: () => ({ structuredContent: { group_by: 'tag', basis: 'my_share', groups: [{ id: 1, name: 'viagem', currency: 'BRL', amount: '40.00', count: 2, percent: '100' }], totals: { BRL: '40.00' } } }) });
    monta(b);
    b.entregar({
      structuredContent: { view: 'breakdown', source_tool: 'reports_breakdown', data: {
        group_by: 'category', basis: 'my_share', totals: { BRL: '100.00' },
        groups: [{ id: 5, name: 'Mercado', currency: 'BRL', amount: '60.00', count: 3, percent: '60' }], others: [] } },
      _meta: { view: 'breakdown', query: { tool: 'reports_breakdown', args: { month: '2026-09', group_by: 'category' } } },
    });
    expect(screen.getByText('Mercado')).toBeInTheDocument();
    await act(async () => {
      fireEvent.change(screen.getByDisplayValue('Categoria'), { target: { value: 'tag' } });
    });
    expect(b.chamadas).toEqual([{ name: 'reports_breakdown', args: { month: '2026-09', group_by: 'tag', basis: 'my_share' } }]);
    await waitFor(() => expect(screen.getByText('viagem')).toBeInTheDocument());
  });

  it('dívidas: "Recebi" registra o acerto na direção certa, com chave de idempotência', async () => {
    const b = ponte({ settlements_create: () => ({ structuredContent: { id: 9 } }), debts_summary: () => ({ structuredContent: { spaces: [], to_pay: '0', to_receive: '0' } }) });
    monta(b);
    b.entregar({
      structuredContent: { view: 'debts', source_tool: 'debts_summary', data: {
        scope: 'accumulated', currency: 'BRL', to_pay: '0.00', to_receive: '45.00',
        spaces: [{ space: { id: 2, name: 'Casa' }, currency: 'BRL', to_pay: '0.00', to_receive: '45.00', balances: [{ person: JOAO, direction: 'owes_you', amount: '45.00' }] }],
        history: [] } },
      _meta: { view: 'debts', query: { tool: 'debts_summary', args: { include_history: true } } },
    });
    expect(screen.getByText('João te deve')).toBeInTheDocument();
    await clica(screen.getByRole('button', { name: 'Recebi' }));
    await clica(screen.getByRole('button', { name: 'Registrar' }));
    const [acerto, releitura] = b.chamadas;
    expect(acerto.name).toBe('settlements_create');
    expect(acerto.args).toMatchObject({ person_id: 2, direction: 'they_paid_me', amount: '45.00', space_id: 2 });
    expect(acerto.args.idempotency_key).toEqual(expect.any(String));
    expect(releitura).toEqual({ name: 'debts_summary', args: { include_history: true } });
    await waitFor(() => expect(screen.getByText('Tudo acertado.')).toBeInTheDocument());
  });

  it('recorrências: pausar manda active=false com a versão', async () => {
    const rec = { id: 4, kind: 'expense', title: 'Netflix', amount: '55.90', currency: 'BRL', frequency: 'monthly', interval: 1, active: true, version: 'r1', space: { id: 2, name: 'Casa' } };
    const b = ponte({ recurring_update: () => ({ structuredContent: { recurring: { ...rec, active: false, version: 'r2' } } }) });
    monta(b);
    b.entregar({ structuredContent: { view: 'recurring', source_tool: 'recurring_list', data: { items: [rec], monthly_my_share: { BRL: '55.90' } } }, _meta: { view: 'recurring' } });
    await clica(screen.getByRole('button', { name: /Netflix/ }));
    await clica(screen.getByRole('button', { name: 'Pausar' }));
    expect(b.chamadas).toEqual([{ name: 'recurring_update', args: { recurring_id: 4, kind: 'expense', active: false, expected_version: 'r1' } }]);
    expect(screen.getByText('pausada')).toBeInTheDocument();
  });
});

describe('Widget: fatura, resumo e recibos', () => {
  const FATURA = {
    card: { id: 1, name: 'Nubank' }, currency: 'BRL', month: '2026-10', total: '500.00', paid: '0.00', balance: '500.00',
    closing_date: '2026-10-03', due_date: '2026-10-10', status: 'open', overdue: false, purchases_count: 9, exists: true,
    by_category: [{ category: 'Mercado', amount: '300.00', count: 2 }],
    purchases: [resumo(7, 'Cama (10/10)', { installment: '10/10', amount: '999.99', statement_amount: '369.00', card: 'Nubank' })],
    payments: [], available_months: ['2026-09', '2026-10'],
  };

  it('fatura: situação em português e o valor da parcela NA FATURA', () => {
    const b = ponte();
    monta(b);
    b.entregar({ structuredContent: FATURA, _meta: { view: 'statement', card_id: 1 } });
    expect(screen.getByText('Fatura de outubro de 2026')).toBeInTheDocument();
    expect(screen.getByText('Aberta')).toBeInTheDocument();
    expect(screen.queryByText('open')).not.toBeInTheDocument();
    expect(screen.getByText(/Cama \(10\/10\)$/)).toBeInTheDocument();
    expect(screen.getByText(/369,00/)).toBeInTheDocument();
    expect(screen.queryByText(/999,99/)).not.toBeInTheDocument();
  });

  it('fatura: Pagar fatura manda cartão, mês, valor, conta e uma chave nova', async () => {
    const b = ponte({ statements_pay: () => ({ structuredContent: {} }), statements_get: () => ({ structuredContent: { ...FATURA, paid: '500.00', balance: '0.00', status: 'paid' } }) });
    monta(b);
    b.entregar({ structuredContent: FATURA, _meta: { view: 'statement', card_id: 1, can_pay: true, accounts: FORM.accounts } });
    await clica(screen.getByRole('button', { name: 'Pagar fatura' }));
    await clica(screen.getByRole('button', { name: 'Pagar' }));
    expect(b.chamadas[0].name).toBe('statements_pay');
    expect(b.chamadas[0].args).toMatchObject({ card_id: 1, month: '2026-10', amount: '500.00', account_id: 3, idempotency_key: expect.any(String) });
    expect(b.chamadas[1]).toEqual({ name: 'statements_get', args: { card_id: 1, month: '2026-10' } });
    await waitFor(() => expect(screen.getByText('Paga')).toBeInTheDocument());
  });

  it('fatura sem permissão de mover caixa não oferece Pagar', () => {
    const b = ponte();
    monta(b);
    b.entregar({ structuredContent: FATURA, _meta: { view: 'statement', card_id: 1, can_pay: false } });
    expect(screen.queryByRole('button', { name: 'Pagar fatura' })).not.toBeInTheDocument();
  });

  it('resumo: resultado, categorias com a porcentagem, e a categoria abre os lançamentos dela', async () => {
    const b = ponte({ transactions_search: () => ({ structuredContent: { items: [resumo(1, 'Aluguel')], next_cursor: null } }) });
    monta(b);
    b.entregar({
      structuredContent: { month: '2026-09', currency: 'BRL', income: '5000.00', consumption: '3000.00', result: '2000.00',
        cash_out: '3000.00', payables_total: '400.00', my_categories: [{ category: 'Moradia', amount: '1500.00' }] },
      _meta: { view: 'summary' },
    });
    expect(screen.getByText('Resultado')).toBeInTheDocument();
    expect(screen.getByText(/50%/)).toBeInTheDocument();
    await clica(screen.getByRole('button', { name: /Moradia/ }));
    expect(b.chamadas[0]).toEqual({ name: 'transactions_search', args: { month: '2026-09', category: 'Moradia' } });
    await waitFor(() => expect(screen.getByText('Aluguel')).toBeInTheDocument());
  });

  it('prévia de massa: confirma mandando só o token', async () => {
    const b = ponte({ transactions_bulk_delete: () => ({ structuredContent: { action: 'delete', count: 3, transaction_ids: [1, 2, 3], attachments_removed: 1 } }) });
    monta(b);
    b.entregar({
      structuredContent: { action: 'delete', count: 3, totals: [{ currency: 'BRL', amount: '90.00', count: 3 }],
        sample: [], ineligible_count: 0, attachments: 1, confirmation_token: 'cfm_cf_abc' },
      _meta: { view: 'bulk_preview' },
    });
    expect(screen.getByText(/1 anexo será apagado para sempre/)).toBeInTheDocument();
    await clica(screen.getByRole('button', { name: 'Confirmar exclusão de 3' }));
    expect(b.chamadas).toEqual([{ name: 'transactions_bulk_delete', args: { confirmation_token: 'cfm_cf_abc' } }]);
    expect(screen.getByText('3 lançamentos excluídos.')).toBeInTheDocument();
    // Anexo apagado não volta: o Desfazer não é oferecido.
    expect(screen.queryByRole('button', { name: /Desfazer/ })).not.toBeInTheDocument();
  });

  it('prévia sem token não oferece confirmar', () => {
    const b = ponte();
    monta(b);
    b.entregar({ structuredContent: { action: 'delete', count: 0, totals: [], sample: [], confirmation_token: null }, _meta: { view: 'bulk_preview' } });
    expect(screen.queryByRole('button', { name: /Confirmar/ })).not.toBeInTheDocument();
  });

  it('recibo de pagamento de fatura: Estornar chama o desfazer do _meta', async () => {
    const b = ponte({ statements_reopen: () => ({ structuredContent: {} }) });
    monta(b);
    b.entregar({
      structuredContent: { card: { id: 1, name: 'Nubank' }, month: '2026-10', amount_paid: '500.00', currency: 'BRL', total: '500.00', paid: '500.00', balance: '0.00', account: { id: 3, name: 'Itaú' } },
      _meta: { view: 'receipt', tool: 'statements_pay', undo: { tool: 'statements_reopen', args: { card_id: 1, month: '2026-10' }, label: 'Estornar' } },
    });
    expect(screen.getByText('Fatura de outubro de 2026 paga')).toBeInTheDocument();
    await clica(screen.getByRole('button', { name: 'Estornar' }));
    expect(b.chamadas).toEqual([{ name: 'statements_reopen', args: { card_id: 1, month: '2026-10' } }]);
    expect(screen.getByRole('status')).toHaveTextContent('Desfeito.');
  });

  it('histórico: valores crus viram texto da tela', () => {
    const b = ponte();
    monta(b);
    b.entregar({
      structuredContent: { view: 'history', source_tool: 'transactions_history', data: { transaction_id: 9, entries: [
        { at: '2026-09-21 09:02', action: 'updated', by: JOAO, via_ai: true, client: 'ChatGPT', detail_only: false,
          changes: [{ field: 'amount', before: '89.90', after: '1099.90' }, { field: 'date', before: '2026-09-20', after: '2026-09-21' }, { field: 'payment_method', before: 'pix', after: 'cash' }] },
      ] } },
      _meta: { view: 'history' },
    });
    expect(screen.getByText('89,90')).toHaveClass('line-through');
    expect(screen.getByText('1.099,90')).toBeInTheDocument();
    expect(screen.getByText('20/09/2026')).toBeInTheDocument();
    expect(screen.getByText('Dinheiro')).toBeInTheDocument();
    expect(screen.getByText(/via IA \(ChatGPT\)/)).toBeInTheDocument();
  });

  it('recibo de ajuste de saldo mostra antes → depois', () => {
    const b = ponte();
    monta(b);
    b.entregar({
      structuredContent: { id: 1, account: { id: 3, name: 'Itaú' }, currency: 'BRL', date: '2026-09-20', previous_balance: '100.00', new_balance: '150.00', adjustment: '50.00' },
      _meta: { view: 'receipt', tool: 'accounts_adjust_balance' },
    });
    expect(screen.getByText('Saldo de Itaú ajustado')).toBeInTheDocument();
    expect(screen.getByText(/100,00/)).toHaveClass('line-through');
  });
});

describe('format', () => {
  it('dinheiro, dia e mês sem passar por fuso', () => {
    expect(money('1234.5')).toMatch(/1\.234,50/);
    expect(day('2026-09-01')).toBe('01/09/2026');
    expect(shortDay('2026-09-01')).toBe('01/09');
    expect(month('2026-09')).toBe('09/2026');
    expect(monthLong('2026-01')).toBe('janeiro de 2026');
    expect(monthLong('2026-12')).toBe('dezembro de 2026');
  });

  it('porcentagem das barras não sai de 0–100 nem divide por zero', () => {
    expect(percent('300', '500')).toBe(60);
    expect(percent('10', '0')).toBe(0);
    expect(percent('900', '500')).toBe(100);
    expect(percent('x', '500')).toBe(0);
  });

  it('plural sem "(s)"', () => {
    expect(plural(1, 'lançamento', 'lançamentos')).toBe('1 lançamento');
    expect(plural(0, 'lançamento', 'lançamentos')).toBe('0 lançamentos');
    expect(plural(3, 'compra', 'compras')).toBe('3 compras');
  });
});
