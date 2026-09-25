/** @jsxImportSource preact */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render } from 'preact';
import { act } from 'preact/test-utils';
import { fireEvent, screen, waitFor, within } from '@testing-library/dom';
import type { Bridge, ToolResultLike } from '../bridge';
import { Widget } from '../Widget';

/**
 * As vistas do componente v4 que o `Widget.test.tsx` não percorre: recibos de
 * escrita, extrato da conta, a pagar, metas, dívidas, rendas, financiamento e
 * importações (ADR 0035 §11).
 *
 * O contrato é o mesmo de lá: cada botão chama a tool de escrita de sempre com os
 * argumentos certos (a chave de idempotência, a versão lida), e a tela mostra o
 * que voltou — inclusive a releitura pela consulta que a desenhou.
 */
type Resposta = (args: Record<string, unknown>) => ToolResultLike;

function ponte(respostas: Record<string, Resposta> = {}) {
  let aoResultado: ((r: ToolResultLike) => void) | null = null;
  const chamadas: Array<{ name: string; args: Record<string, unknown> }> = [];
  const b = {
    chamadas,
    onResult: (cb: (r: ToolResultLike) => void) => { aoResultado = cb; },
    onTheme: () => {},
    callTool: vi.fn(async (name: string, args: Record<string, unknown>) => {
      chamadas.push({ name, args });
      return respostas[name]?.(args) ?? { structuredContent: {} };
    }),
    openLink: vi.fn(),
    updateModelContext: vi.fn(async () => {}),
    entregar: (r: ToolResultLike) => act(() => aoResultado?.(r)),
  };
  return b satisfies Bridge;
}

let raiz: HTMLElement;
function monta(b: Bridge) {
  raiz = document.createElement('div');
  document.body.appendChild(raiz);
  act(() => render(<Widget bridge={b} />, raiz));
}

afterEach(() => {
  if (raiz) {
    render(null, raiz);
    raiz.remove();
  }
});

const clica = async (el: Element) => {
  await act(async () => {
    fireEvent.click(el);
  });
};
const digita = async (el: Element, valor: string) => {
  await act(async () => {
    fireEvent.input(el, { target: { value: valor } });
  });
};
const botao = (nome: string | RegExp) => screen.getByRole('button', { name: nome });
const CASA = { id: 2, name: 'Casa' };

describe('Vistas: recibos de escrita', () => {
  const casos: Array<[string, Record<string, unknown>, RegExp]> = [
    ['statements_pay', { month: '2026-09', card: { id: 1, name: 'Nubank' }, amount_paid: '500.00', currency: 'BRL', total: '500.00', paid: '500.00', balance: '0.00', account: { id: 3, name: 'Itaú' } }, /Fatura de setembro de 2026 paga/],
    ['statements_reopen', { month: '2026-09', card: { id: 1, name: 'Nubank' }, reversed_payments: [{}, {}], balance: '500.00', currency: 'BRL' }, /reaberta/],
    ['transfers_create', { date: '2026-09-20', from_account: { id: 1, name: 'Itaú' }, to_account: { id: 2, name: 'Wise' }, from_amount: '100.00', to_amount: '19.00', from_currency: 'BRL', to_currency: 'USD' }, /Transferência registrada/],
    ['transfers_delete', { deleted: { from_account: { id: 1, name: 'Itaú' }, to_account: { id: 2, name: 'Poupança' }, from_amount: '100.00', from_currency: 'BRL' } }, /Transferência excluída/],
    ['settlements_create', { space: CASA, date: '2026-09-20', payer: { id: 2, name: 'João' }, receiver: { id: 1, name: 'Alice' }, amount: '45.00', currency: 'BRL', month: '2026-09' }, /Acerto registrado/],
    ['settlements_delete', { deleted: { payer: { id: 2, name: 'João' }, receiver: { id: 1, name: 'Alice' }, amount: '45.00', currency: 'BRL' } }, /Acerto excluído/],
    ['accounts_adjust_balance', { account: { id: 3, name: 'Itaú' }, date: '2026-09-20', previous_balance: '100.00', new_balance: '150.00', adjustment: '50.00', currency: 'BRL' }, /Saldo de Itaú ajustado/],
    ['budgets_set', { created: true, category: { id: 5, name: 'Mercado' }, month: '2026-09', space: CASA, scope: 'personal', amount: '800.00' }, /Meta criada: Mercado/],
    ['categories_create', { kind: 'tag', name: 'viagem', space: CASA }, /Tag criada: #viagem/],
    ['attachments_add', { transaction_id: 7, attachment: { filename: 'nota.png' } }, /Anexo adicionado/],
    ['attachments_delete', { transaction_id: 7, deleted: { filename: 'nota.png' } }, /Anexo removido/],
    ['ferramenta_sem_recibo', {}, /Feito/],
  ];

  it.each(casos)('%s: diz o que foi feito', (tool, dados, titulo) => {
    const b = ponte();
    monta(b);
    b.entregar({ structuredContent: dados, _meta: { view: 'receipt', tool } });
    expect(screen.getByText(titulo)).toBeInTheDocument();
  });

  it('transferência entre moedas mostra o que chegou; acerto do mês mostra o mês', () => {
    const b = ponte();
    monta(b);
    b.entregar({ structuredContent: casos[2][1], _meta: { view: 'receipt', tool: 'transfers_create' } });
    expect(screen.getByText('Chegou')).toBeInTheDocument();
  });

  it('categoria renomeada mostra antes → depois; excluída, o nome riscado no título', () => {
    const b = ponte();
    monta(b);
    b.entregar({ structuredContent: { kind: 'category', name: 'Alimentação fora', previous_name: 'Restaurantes', space: CASA }, _meta: { view: 'receipt', tool: 'categories_update' } });
    expect(screen.getByText('Categoria atualizada')).toBeInTheDocument();
    expect(screen.getByText('Restaurantes')).toHaveClass('line-through');
  });

  it('categoria excluída e recibo repetido', () => {
    const b = ponte();
    monta(b);
    b.entregar({ structuredContent: { kind: 'tag', name: 'viagem', deleted: true, space: CASA, replayed: true }, _meta: { view: 'receipt', tool: 'categories_update' } });
    expect(screen.getByText('Tag excluída: viagem')).toBeInTheDocument();
    expect(screen.getByText(/nada foi duplicado/)).toBeInTheDocument();
  });

  it('Desfazer chama a tool do _meta; Abrir no app abre o link', async () => {
    const b = ponte();
    monta(b);
    b.entregar({
      structuredContent: { ...casos[4][1], app_url: 'https://app.example/acertos' },
      _meta: { view: 'receipt', tool: 'settlements_create', undo: { tool: 'settlements_delete', args: { settlement_id: 9 } } },
    });
    await clica(botao('Abrir no app'));
    expect(b.openLink).toHaveBeenCalledWith('https://app.example/acertos');
    await clica(botao('Desfazer'));
    expect(b.chamadas).toEqual([{ name: 'settlements_delete', args: { settlement_id: 9 } }]);
    expect(screen.getByText('Desfeito.')).toBeInTheDocument();
  });
});

describe('Vistas: extrato da conta e caixa', () => {
  const EXTRATO = {
    mode: 'account', account: { id: 3, name: 'Itaú' }, month: '2026-09', currency: 'BRL', balance: '1500.00',
    cash_in: '5000.00', cash_out: '3500.00', net_cash: '1500.00', total_count: 3, next_cursor: 'c2',
    entries: [
      { date: '2026-09-05', source: 'income', title: 'Salário', amount: '5000.00', currency: 'BRL', running_balance: '5000.00' },
      { date: '2026-09-10', source: 'statement_payment', title: 'Fatura Nubank', amount: '-3500.00', currency: 'BRL', running_balance: '1500.00', counterparty: 'Nubank' },
    ],
    app_url: 'https://app.example/contas/3',
  };

  it('mostra saldo, entradas e saídas, e troca o mês pela mesma consulta', async () => {
    const b = ponte({ accounts_statement: (a) => ({ structuredContent: { ...EXTRATO, month: a.month, entries: [], total_count: 0, next_cursor: null } }) });
    monta(b);
    b.entregar({ structuredContent: { view: 'account', source_tool: 'accounts_statement', data: EXTRATO }, _meta: { view: 'account', query: { tool: 'accounts_statement', args: { account: 'Itaú', month: '2026-09' } } } });
    expect(screen.getByText('Salário')).toBeInTheDocument();
    expect(screen.getByText(/Pagamento de fatura · Nubank/)).toBeInTheDocument();
    expect(screen.getByText('Entrou')).toBeInTheDocument();
    await clica(botao('Mês anterior'));
    expect(b.chamadas[0]).toEqual({ name: 'accounts_statement', args: { account_id: 3, month: '2026-08' } });
    await waitFor(() => expect(screen.getByText('Nenhuma movimentação no mês.')).toBeInTheDocument());
  });

  it('Carregar mais pede a próxima página com o cursor', async () => {
    const b = ponte({ accounts_statement: () => ({ structuredContent: { entries: [{ date: '2026-09-01', source: 'adjustment', title: 'Ajuste', amount: '10.00', currency: 'BRL' }], next_cursor: null } }) });
    monta(b);
    b.entregar({ structuredContent: EXTRATO, _meta: { view: 'account', query: { tool: 'accounts_statement', args: { account_id: 3 } } } });
    await clica(botao('Carregar mais'));
    expect(b.chamadas[0].args).toMatchObject({ account_id: 3, cursor: 'c2' });
    await waitFor(() => expect(screen.getByText('Ajuste')).toBeInTheDocument());
  });

  it('Ajustar saldo manda o saldo do banco com chave nova e relê o extrato', async () => {
    const b = ponte({
      accounts_adjust_balance: () => ({ structuredContent: { previous_balance: '1500.00', new_balance: '1450.00' } }),
      accounts_statement: () => ({ structuredContent: { ...EXTRATO, balance: '1450.00' } }),
    });
    monta(b);
    b.entregar({ structuredContent: EXTRATO, _meta: { view: 'account', accounts: [{ id: 3, name: 'Itaú', currency: 'BRL' }] } });
    await clica(botao('Ajustar saldo'));
    await digita(screen.getByLabelText(/Saldo que o banco mostra/), '145000');
    await clica(botao('Ajustar'));
    expect(b.chamadas[0].name).toBe('accounts_adjust_balance');
    expect(b.chamadas[0].args).toMatchObject({ account_id: 3, real_balance: '1450.00', idempotency_key: expect.any(String) });
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Saldo ajustado'));
    expect(b.chamadas[1].name).toBe('accounts_statement');
  });

  it('caixa do mês (sem conta) não oferece ajuste; erro na troca de mês vira aviso', async () => {
    const b = ponte({ accounts_statement: () => ({ isError: true, content: [{ type: 'text', text: 'x\n{"error":{"code":"NOT_FOUND","message":"Mês fora do alcance."}}' }] }) });
    monta(b);
    b.entregar({ structuredContent: { ...EXTRATO, mode: 'cash', account: null }, _meta: { view: 'cash' } });
    expect(screen.getByText('Caixa do mês')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Ajustar saldo' })).not.toBeInTheDocument();
    await clica(botao('Próximo mês'));
    await waitFor(() => expect(screen.getByText('Mês fora do alcance.')).toBeInTheDocument());
  });
});

describe('Vistas: a pagar e metas', () => {
  const A_PAGAR = {
    month: '2026-09', currency: 'BRL', bills_total: '300.00', overdue_total: '120.00',
    bills: [{ transaction_id: 11, space: CASA, title: 'Luz', due_date: '2026-09-10', amount: '120.00', currency: 'BRL', overdue: true, installment: null }],
    card_bills: [{ card: { id: 1, name: 'Nubank' }, statement_id: 5, month: '2026-09', due_date: '2026-09-15', amount: '500.00', overdue: false }],
    financings: [
      { financing_id: 8, title: 'Carro', next_due_date: '2026-09-20', next_amount: '900.00', outstanding: '9000.00', remaining_installments: 10, overdue_count: 1 },
      { financing_id: 9, title: 'Quitado', next_due_date: null, next_amount: null, outstanding: '0.00', remaining_installments: 0, overdue_count: 0 },
    ],
  };
  const consulta = { tool: 'payables_list', args: { month: '2026-09' } };

  it('avisa o vencido e paga a fatura pela conta escolhida, relendo a lista', async () => {
    const b = ponte({ statements_pay: () => ({ structuredContent: {} }), payables_list: () => ({ structuredContent: { ...A_PAGAR, card_bills: [], overdue_total: '0' } }) });
    monta(b);
    b.entregar({ structuredContent: A_PAGAR, _meta: { view: 'payables', query: consulta, accounts: [{ id: 3, name: 'Itaú', currency: 'BRL' }] } });
    expect(screen.getByText(/vencidos/)).toBeInTheDocument();
    const fatura = screen.getByText('Nubank').closest('li')!;
    await clica(within(fatura).getByRole('button', { name: 'Pagar' }));
    await clica(within(fatura).getByRole('button', { name: /Pagar R\$/ }));
    expect(b.chamadas[0]).toMatchObject({ name: 'statements_pay', args: { card_id: 1, month: '2026-09', account_id: 3 } });
    expect(b.chamadas[1]).toEqual({ name: 'payables_list', args: { month: '2026-09' } });
    await waitFor(() => expect(screen.getByText('Fatura do Nubank paga.')).toBeInTheDocument());
  });

  it('marca a conta como paga e paga a parcela do financiamento', async () => {
    const b = ponte({ payables_list: () => ({ structuredContent: A_PAGAR }) });
    monta(b);
    b.entregar({ structuredContent: A_PAGAR, _meta: { view: 'payables', query: consulta } });
    await clica(botao('Paga'));
    expect(b.chamadas[0]).toEqual({ name: 'transactions_update', args: { transaction_id: 11, settled: true } });
    const carro = screen.getByText('Carro').closest('li')!;
    await clica(within(carro).getByRole('button', { name: 'Pagar' }));
    expect(b.chamadas.map((c) => c.name)).toContain('financings_installment');
    expect(screen.getByText(/1 em atraso/)).toBeInTheDocument();
  });

  it('sem nada a pagar diz isso', () => {
    const b = ponte();
    monta(b);
    b.entregar({ structuredContent: { month: '2026-09', currency: 'BRL', bills_total: '0', bills: [], card_bills: [], financings: [] }, _meta: { view: 'payables' } });
    expect(screen.getByText('Nada a pagar neste mês.')).toBeInTheDocument();
  });

  it('metas: estourada em vermelho, editar manda budgets_set com o escopo', async () => {
    const METAS = {
      month: '2026-09', budgets: [
        { id: 1, space: CASA, category: 'Mercado', scope: 'personal', planned: '500.00', spent: '600.00', remaining: '-100.00', over_budget: true, currency: 'BRL' },
        { id: 2, space: CASA, category: 'Lazer', scope: 'workspace', planned: '200.00', spent: '180.00', remaining: '20.00', over_budget: false, currency: 'BRL' },
      ],
    };
    const b = ponte({ budgets_set: () => ({ structuredContent: {} }), budgets_list: () => ({ structuredContent: METAS }) });
    monta(b);
    b.entregar({ structuredContent: METAS, _meta: { view: 'budgets', query: { tool: 'budgets_list', args: { month: '2026-09' } } } });
    expect(screen.getByText(/1 estourada/)).toBeInTheDocument();
    expect(screen.getByText(/Estourou/)).toBeInTheDocument();
    expect(screen.getByText(/Sobram/)).toBeInTheDocument();
    await clica(botao('Editar a meta de Lazer'));
    await digita(screen.getByLabelText('Meta do mês'), '25000');
    await clica(botao('Salvar'));
    expect(b.chamadas[0]).toEqual({ name: 'budgets_set', args: { space_id: 2, category: 'Lazer', amount: '250.00', month: '2026-09', scope: 'space' } });
    await waitFor(() => expect(screen.getByText(/Meta de Lazer agora é/)).toBeInTheDocument());
  });

  it('metas: mês sem meta', () => {
    const b = ponte();
    monta(b);
    b.entregar({ structuredContent: { month: '2026-09', budgets: [] }, _meta: { view: 'budgets' } });
    expect(screen.getByText('Nenhuma meta neste mês.')).toBeInTheDocument();
  });
});

describe('Vistas: dívidas', () => {
  const DIVIDAS = {
    scope: 'month', month: '2026-09', currency: 'BRL', to_pay: '30.00', to_receive: '0.00',
    spaces: [{ space: CASA, currency: 'BRL', to_pay: '30.00', to_receive: '0.00', balances: [{ person: { id: 2, name: 'João' }, direction: 'you_owe', amount: '30.00' }] }],
    history: [{ id: 4, space: CASA, counterparty: { id: 2, name: 'João' }, direction: 'paid', amount: '10.00', currency: 'BRL', date: '2026-09-01', note: 'pix' }],
  };

  it('"Paguei" no retrato do mês manda o mês; o histórico exclui acerto com dois cliques', async () => {
    const b = ponte({ debts_summary: () => ({ structuredContent: DIVIDAS }) });
    monta(b);
    b.entregar({ structuredContent: DIVIDAS, _meta: { view: 'debts', query: { tool: 'debts_summary', args: { month: '2026-09' } } } });
    expect(screen.getByText(/Retrato de setembro/)).toBeInTheDocument();
    await clica(botao('Paguei'));
    await clica(botao('Registrar'));
    expect(b.chamadas[0].args).toMatchObject({ person_id: 2, direction: 'i_paid_them', amount: '30.00', month: '2026-09' });
    await clica(screen.getByRole('button', { name: /^Acertos/ }));
    await clica(botao('Excluir acerto'));
    await clica(within(screen.getByText('Você pagou João').closest('li')!).getByRole('button', { name: 'Excluir' }));
    expect(b.chamadas.map((c) => c.name)).toContain('settlements_delete');
  });
});

describe('Vistas: rendas e financiamento', () => {
  const RENDA = { id: 3, title: 'Freela', amount: '800.00', currency: 'BRL', date: '2026-09-10', status: 'expected', category: 'Trabalho', account: { id: 3, name: 'Itaú' }, recurring: true, version: 'r1' };

  it('marca a renda como recebida com a versão, exclui e restaura', async () => {
    const b = ponte({
      income_update: () => ({ structuredContent: { income: { ...RENDA, status: 'received', received_on: '2026-09-11' } } }),
      income_delete: () => ({ structuredContent: { deleted: RENDA } }),
      income_restore: () => ({ structuredContent: { income: { ...RENDA, status: 'received' } } }),
    });
    monta(b);
    b.entregar({ structuredContent: { month: '2026-09', incomes: [RENDA], currency_totals: { BRL: '800.00' } }, _meta: { view: 'income' } });
    expect(screen.getByText('Prevista')).toBeInTheDocument();
    await clica(botao('Marcar Freela como recebida'));
    expect(b.chamadas[0]).toEqual({ name: 'income_update', args: { income_id: 3, status: 'received', expected_version: 'r1' } });
    expect(screen.getByText('Recebida')).toBeInTheDocument();
    await clica(botao('Excluir Freela'));
    expect(screen.getByText('excluída')).toBeInTheDocument();
    await clica(botao('Restaurar Freela'));
    expect(b.chamadas.map((c) => c.name)).toEqual(['income_update', 'income_delete', 'income_restore']);
  });

  it('renda editada mostra antes → depois e a conversão; mês sem renda', () => {
    const b = ponte();
    monta(b);
    b.entregar({
      structuredContent: {
        income: { ...RENDA, amount: '900.00', original_amount: '180.00', original_currency: 'USD' },
        previous: RENDA, changed: ['amount', 'status', 'account'],
      },
      _meta: { view: 'income', mode: 'updated' },
    });
    expect(screen.getByText('Valor')).toBeInTheDocument();
    expect(screen.getByText(/convertidos/)).toBeInTheDocument();
    render(null, raiz);
    const b2 = ponte();
    monta(b2);
    b2.entregar({ structuredContent: { month: '2026-09', incomes: [] }, _meta: { view: 'income' } });
    expect(screen.getByText('Nenhuma renda no mês.')).toBeInTheDocument();
  });

  const FIN = {
    id: 8, title: 'Carro', status: 'active', currency: 'BRL', amount: '20000.00', monthly_rate: '0.0149', start_date: '2026-01-10',
    installments: 24, paid_installments: 1, remaining_installments: 23, outstanding: '18000.00', next_due_date: '2026-10-10',
    next_amount: '950.00', overdue_count: 1, app_url: 'https://app.example/financiamentos/8',
  };
  const CRONO = [
    { number: 1, due_date: '2026-02-10', principal: '800.00', interest: '150.00', total: '950.00', remaining_balance: '19200.00', paid: true, paid_on: '2026-02-09', overdue: false },
    { number: 2, due_date: '2026-03-10', principal: '810.00', interest: '140.00', total: '950.00', remaining_balance: '18390.00', paid: false, overdue: true },
    { number: 3, due_date: '2026-04-10', principal: '820.00', interest: '130.00', total: '950.00', remaining_balance: '17570.00', paid: false, overdue: false },
  ];

  it('cronograma: paga a próxima em aberto e desfaz a paga', async () => {
    const b = ponte({ financings_installment: () => ({ structuredContent: {} }) });
    monta(b);
    b.entregar({ structuredContent: { financing: FIN, schedule: CRONO, next_cursor: null }, _meta: { view: 'financing' } });
    expect(screen.getByText(/1,49% a\.m\./)).toBeInTheDocument();
    expect(screen.getByText(/1 parcela atrasada/)).toBeInTheDocument();
    const segunda = screen.getByText('Parcela 2').closest('li')!;
    await clica(within(segunda).getByRole('button', { name: 'Pagar' }));
    expect(b.chamadas[0]).toEqual({ name: 'financings_installment', args: { action: 'pay', financing_id: 8, installment: 2 } });
    await clica(botao('Desfazer pagamento da parcela 1'));
    expect(b.chamadas[1].args).toMatchObject({ action: 'unpay', installment: 1 });
    await clica(botao('Abrir no app'));
    expect(b.openLink).toHaveBeenCalledWith(FIN.app_url);
  });

  it('resultado de pagar parcela avisa e oferece Desfazer; lista vazia', () => {
    const b = ponte();
    monta(b);
    b.entregar({ structuredContent: { financing: FIN, action: 'pay', installment: 2 }, _meta: { tool: 'financings_installment', undo: { tool: 'financings_installment', args: { action: 'unpay', financing_id: 8, installment: 2 } } } });
    expect(screen.getByText('Parcela 2 paga.')).toBeInTheDocument();
    expect(botao('Desfazer')).toBeInTheDocument();
    render(null, raiz);
    const b2 = ponte();
    monta(b2);
    b2.entregar({ structuredContent: { financings: [] }, _meta: { view: 'financing' } });
    expect(screen.getByText('Nenhum financiamento.')).toBeInTheDocument();
  });
});

describe('Vistas: importações e histórico', () => {
  const LOTE = { id: 5, space: CASA, filename: 'setembro.csv', imported_on: '2026-09-20', total_rows: 4, imported: 2, ignored: 1, duplicates: 1, skipped: 0, live_transactions: 2 };

  it('lista de lotes; o lote aberto mostra as linhas com a situação de cada uma', () => {
    const b = ponte();
    monta(b);
    b.entregar({ structuredContent: { batches: [LOTE] }, _meta: { view: 'imports', query: { tool: 'imports_list', args: {} } } });
    expect(screen.getByText('setembro.csv')).toBeInTheDocument();
    render(null, raiz);
    const b2 = ponte();
    monta(b2);
    b2.entregar({
      structuredContent: {
        batches: [LOTE], rows: [
          { line: 2, date: '2026-09-01', title: 'Mercado', amount: '50.00', status: 'imported', transaction_id: 9 },
          { line: 3, title: 'Pix', status: 'duplicate', reason: 'já importada' },
          { line: 4, status: 'ignored' },
        ],
      },
      _meta: { view: 'imports', query: { tool: 'imports_list', args: { batch_id: 5 } } },
    });
    expect(screen.getByText('Importação #5')).toBeInTheDocument();
    expect(screen.getByText('duplicada')).toBeInTheDocument();
    expect(screen.getByText('Linha 4')).toBeInTheDocument();
  });

  it('resultado da importação com Desfazer: prévia do imports_undo, depois o token (ADR 0037)', async () => {
    const b = ponte({
      imports_undo: (a) => ({
        structuredContent: a.confirmation_token
          ? { batch_id: 5, undone: { expense: 2 } }
          : { batch_id: 5, confirmation_token: 'tok', will_undo: { expense: 2 }, attachments: 1 },
      }),
    });
    monta(b);
    b.entregar({
      structuredContent: { batch_id: 5, imported: 2, duplicate: 1, ignored: 1, skipped: 1, space: CASA, replayed: true },
      _meta: { view: 'imports', tool: 'imports_commit', undo: { tool: 'imports_undo', args: { batch_id: 5 } } },
    });
    expect(screen.getByText('2 lançamentos importados')).toBeInTheDocument();
    expect(screen.getByText(/nada foi duplicado/)).toBeInTheDocument();
    await clica(botao('Desfazer importação'));
    expect(b.chamadas[0]).toEqual({ name: 'imports_undo', args: { batch_id: 5 } });
    expect(screen.getByText(/1 recibo anexado será apagado/)).toBeInTheDocument();
    await clica(botao('Confirmar e desfazer'));
    expect(b.chamadas[1]).toEqual({ name: 'imports_undo', args: { batch_id: 5, confirmation_token: 'tok' } });
    expect(screen.getByRole('status')).toHaveTextContent('Importação desfeita: 2 despesas');
  });

  it('histórico de um lançamento', () => {
    const b = ponte();
    monta(b);
    b.entregar({
      structuredContent: { transaction_id: 7, entries: [{ at: '2026-09-20T12:00:00Z', action: 'created', actor: { id: 1, name: 'Alice' }, via_ai: true, changes: [] }] },
      _meta: { view: 'history' },
    });
    expect(screen.getByText('Histórico do lançamento #7')).toBeInTheDocument();
  });
});
