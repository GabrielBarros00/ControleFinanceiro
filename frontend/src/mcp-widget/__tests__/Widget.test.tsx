/** @jsxImportSource preact */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render } from 'preact';
import { act } from 'preact/test-utils';
import { fireEvent, screen, waitFor } from '@testing-library/dom';
import type { Bridge, ToolResultLike } from '../bridge';
import { Widget } from '../Widget';
import { day, money, month, monthLong, percent, plural, shortDay } from '../format';

/**
 * O componente MCP Apps é progressive enhancement: ele só REDESENHA o
 * `structuredContent` que a tool já devolveu. Estes testes usam uma ponte falsa
 * (a do host é postMessage) e travam as quatro vistas, o tema do host e o botão
 * de confirmar a massa — que precisa mandar SÓ o token da prévia.
 *
 * Renderiza com o Preact de verdade (o mesmo do build), não com o React do SPA.
 */
function ponte(): Bridge & { entregar(r: ToolResultLike): void; tema(t: 'light' | 'dark'): void; chamadas: unknown[] } {
  let aoResultado: ((r: ToolResultLike) => void) | null = null;
  let aoTema: ((t: 'light' | 'dark') => void) | null = null;
  const chamadas: unknown[] = [];
  return {
    chamadas,
    onResult: (cb) => { aoResultado = cb; },
    onTheme: (cb) => { aoTema = cb; },
    callTool: vi.fn(async (name: string, args: Record<string, unknown>) => {
      chamadas.push({ name, args });
      return { structuredContent: { count: 3 } };
    }),
    openLink: vi.fn(),
    entregar: (r) => act(() => aoResultado?.(r)),
    tema: (t) => act(() => aoTema?.(t)),
  };
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

const TX = {
  id: 1, title: 'Jantar', amount: '120.01', currency: 'BRL', date: '2026-09-22', status: 'confirmed', settled: true,
  space: { id: 2, name: 'Casa' }, category: { id: 5, name: 'Alimentação' }, my_share: '60.01',
  split: [
    { person: { id: 1, name: 'Alice' }, amount: '60.01', is_me: true },
    { person: { id: 2, name: 'João' }, amount: '60.00' },
  ],
  app_url: 'https://app.example/w/2/transactions',
};

describe('Widget', () => {
  it('enquanto o resultado não chega, mostra a silhueta (sem texto piscando)', () => {
    monta(ponte());
    expect(screen.getByLabelText('Carregando')).toHaveAttribute('aria-busy', 'true');
  });

  it('lançamento: valor, divisão, sua parte e abrir no app', () => {
    const b = ponte();
    monta(b);
    b.entregar({ structuredContent: { transaction: TX }, _meta: { view: 'transaction', app_url: TX.app_url } });
    expect(screen.getByText('Jantar')).toBeInTheDocument();
    expect(screen.getByText('Alice (você)')).toBeInTheDocument();
    expect(screen.getByText('Sua parte')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Abrir no Controle Financeiro/ }));
    expect(b.openLink).toHaveBeenCalledWith(TX.app_url);
  });

  it('lançamento convertido mostra o valor original', () => {
    const b = ponte();
    monta(b);
    b.entregar({
      structuredContent: { transaction: { ...TX, foreign: { original_amount: '50.00', original_currency: 'USD' } } },
      _meta: { view: 'transaction' },
    });
    expect(screen.getByText(/US\$\s?50,00 convertidos/)).toBeInTheDocument();
  });

  it('fatura: situação em português, saldo, categorias e o valor na moeda do CARTÃO', () => {
    const b = ponte();
    monta(b);
    b.entregar({
      structuredContent: {
        card: { id: 1, name: 'Nubank' }, currency: 'BRL', month: '2026-10', total: '500.00', balance: '500.00',
        due_date: '2026-10-10', status: 'open', overdue: false, purchases_count: 9,
        by_category: [{ category: 'Mercado', amount: '300.00', count: 2 }],
        purchases: [{ id: 7, title: 'Cama (10/10)', date: '2026-09-23', amount: '999.99', currency: 'BRL',
                      installment: '10/10', statement_amount: '369.00' }],
      },
      _meta: { view: 'statement' },
    });
    expect(screen.getByText('Fatura de outubro de 2026')).toBeInTheDocument();
    expect(screen.getByText('Aberta')).toBeInTheDocument();
    expect(screen.queryByText('open')).not.toBeInTheDocument();
    expect(screen.getByText('Mercado')).toBeInTheDocument();
    expect(screen.getByText(/60%/)).toBeInTheDocument();
    // O título da parcela já traz o "(10/10)": nada de "Cama (10/10) (10/10)".
    expect(screen.getByText(/Cama \(10\/10\)$/)).toBeInTheDocument();
    expect(screen.getByText(/369,00/)).toBeInTheDocument();
    expect(screen.queryByText(/999,99/)).not.toBeInTheDocument();
    expect(screen.getByText('e mais 8 compras no app')).toBeInTheDocument();
  });

  it('fatura vencida e fatura quitada', () => {
    const b = ponte();
    monta(b);
    b.entregar({
      structuredContent: { card: { id: 1, name: 'C6' }, currency: 'BRL', month: '2026-08', total: '80.00', balance: '0.00',
        due_date: '2026-08-10', status: 'paid', overdue: false, by_category: [], purchases: [] },
      _meta: { view: 'statement' },
    });
    expect(screen.getByText('Paga')).toBeInTheDocument();
    expect(screen.getByText('Quitada')).toBeInTheDocument();
    b.entregar({
      structuredContent: { card: { id: 1, name: 'C6' }, currency: 'BRL', month: '2026-08', total: '80.00', balance: '80.00',
        due_date: '2026-08-10', status: 'closed', overdue: true, by_category: [], purchases: [] },
      _meta: { view: 'statement' },
    });
    expect(screen.getByText('Vencida')).toBeInTheDocument();
    expect(screen.getByText('Falta pagar')).toBeInTheDocument();
  });

  it('resumo do mês: resultado em destaque e categorias com a porcentagem do consumo', () => {
    const b = ponte();
    monta(b);
    b.entregar({
      structuredContent: { month: '2026-09', currency: 'BRL', income: '5000.00', consumption: '3000.00', result: '2000.00',
        cash_out: '3000.00', payables_total: '400.00', my_categories: [{ category: 'Moradia', amount: '1500.00' }] },
      _meta: { view: 'summary' },
    });
    expect(screen.getByText('setembro de 2026')).toBeInTheDocument();
    expect(screen.getByText('Resultado do mês')).toBeInTheDocument();
    expect(screen.getByText('Moradia')).toBeInTheDocument();
    expect(screen.getByText(/50%/)).toBeInTheDocument();
  });

  it('prévia de massa: confirma mandando só o token', async () => {
    const b = ponte();
    monta(b);
    b.entregar({
      structuredContent: { action: 'delete', count: 3, totals: [{ currency: 'BRL', amount: '90.00', count: 3 }],
        sample: [], ineligible_count: 0, attachments: 1, confirmation_token: 'cfm_cf_abc' },
      _meta: { view: 'bulk_preview' },
    });
    expect(screen.getByText(/1 anexo será apagado para sempre/)).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Confirmar exclusão' }));
    });
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('3 lançamentos excluídos.'));
    expect(b.chamadas).toEqual([{ name: 'transactions_bulk_delete', args: { confirmation_token: 'cfm_cf_abc' } }]);
  });

  it('prévia sem token não oferece confirmar', () => {
    const b = ponte();
    monta(b);
    b.entregar({ structuredContent: { action: 'delete', count: 0, totals: [], sample: [], confirmation_token: null }, _meta: { view: 'bulk_preview' } });
    expect(screen.queryByRole('button', { name: /Confirmar/ })).not.toBeInTheDocument();
  });

  it('segue o tema do host', () => {
    const b = ponte();
    monta(b);
    b.tema('dark');
    expect(document.documentElement.classList.contains('dark')).toBe(true);
    b.tema('light');
    expect(document.documentElement.classList.contains('dark')).toBe(false);
  });

  it('resultado de erro não desenha nada (o texto já está na conversa)', () => {
    const b = ponte();
    const container = monta(b);
    b.entregar({ isError: true, structuredContent: null });
    expect(container).toBeEmptyDOMElement();
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
