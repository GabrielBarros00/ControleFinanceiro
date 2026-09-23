import { describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { Bridge, ToolResultLike } from '../bridge';
import { Widget } from '../Widget';
import { day, money, month } from '../format';

/**
 * O componente MCP Apps é progressive enhancement: ele só REDESENHA o
 * `structuredContent` que a tool já devolveu. Estes testes usam uma ponte falsa
 * (a do host é postMessage) e travam as quatro vistas, o tema do host e o botão
 * de confirmar a massa — que precisa mandar SÓ o token da prévia.
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
  it('lançamento: valor, divisão, sua parte e abrir no app', () => {
    const b = ponte();
    render(<Widget bridge={b} />);
    b.entregar({ structuredContent: { transaction: TX }, _meta: { view: 'transaction', app_url: TX.app_url } });
    expect(screen.getByText('Jantar')).toBeInTheDocument();
    expect(screen.getByText('Alice (você)')).toBeInTheDocument();
    expect(screen.getByText('Sua parte')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Abrir no Controle Financeiro/ }));
    expect(b.openLink).toHaveBeenCalledWith(TX.app_url);
  });

  it('fatura: total, saldo e categorias', () => {
    const b = ponte();
    render(<Widget bridge={b} />);
    b.entregar({
      structuredContent: {
        card: { id: 1, name: 'Nubank' }, currency: 'BRL', month: '2026-10', total: '500.00', balance: '500.00',
        due_date: '2026-10-10', status: 'open', overdue: false,
        by_category: [{ category: 'Mercado', amount: '300.00', count: 2 }], purchases: [],
      },
      _meta: { view: 'statement' },
    });
    expect(screen.getByText(/Fatura 10\/2026 · Nubank/)).toBeInTheDocument();
    expect(screen.getByText('Mercado')).toBeInTheDocument();
  });

  it('resumo do mês', () => {
    const b = ponte();
    render(<Widget bridge={b} />);
    b.entregar({
      structuredContent: { month: '2026-09', currency: 'BRL', income: '5000.00', consumption: '3200.00', result: '1800.00',
        cash_out: '3000.00', payables_total: '400.00', my_categories: [{ category: 'Moradia', amount: '1500.00' }] },
      _meta: { view: 'summary' },
    });
    expect(screen.getByText('Resumo de 09/2026')).toBeInTheDocument();
    expect(screen.getByText('Moradia')).toBeInTheDocument();
  });

  it('prévia de massa: confirma mandando só o token', async () => {
    const b = ponte();
    render(<Widget bridge={b} />);
    b.entregar({
      structuredContent: { action: 'delete', count: 3, totals: [{ currency: 'BRL', amount: '90.00', count: 3 }],
        sample: [], ineligible_count: 0, attachments: 1, confirmation_token: 'cfm_cf_abc' },
      _meta: { view: 'bulk_preview' },
    });
    expect(screen.getByText(/1 anexo\(s\) serão apagados/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar exclusão' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('3 lançamento(s) excluído(s).'));
    expect(b.chamadas).toEqual([{ name: 'transactions_bulk_delete', args: { confirmation_token: 'cfm_cf_abc' } }]);
  });

  it('prévia sem token não oferece confirmar', () => {
    const b = ponte();
    render(<Widget bridge={b} />);
    b.entregar({ structuredContent: { action: 'delete', count: 0, totals: [], sample: [], confirmation_token: null }, _meta: { view: 'bulk_preview' } });
    expect(screen.queryByRole('button', { name: /Confirmar/ })).not.toBeInTheDocument();
  });

  it('segue o tema do host', () => {
    const b = ponte();
    render(<Widget bridge={b} />);
    b.tema('dark');
    expect(document.documentElement.classList.contains('dark')).toBe(true);
    b.tema('light');
    expect(document.documentElement.classList.contains('dark')).toBe(false);
  });

  it('resultado de erro não desenha nada (o texto já está na conversa)', () => {
    const b = ponte();
    const { container } = render(<Widget bridge={b} />);
    b.entregar({ isError: true, structuredContent: null });
    expect(container).toBeEmptyDOMElement();
  });
});

describe('format', () => {
  it('dinheiro, dia e mês sem passar por fuso', () => {
    expect(money('1234.5')).toMatch(/1\.234,50/);
    expect(day('2026-09-01')).toBe('01/09/2026');
    expect(month('2026-09')).toBe('09/2026');
  });
});
