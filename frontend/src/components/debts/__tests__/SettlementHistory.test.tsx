import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { SettlementHistory, type HistoryRow } from '../SettlementHistory';

/**
 * O histórico — o único lugar que lista acertos, nas duas telas.
 *
 * `CardsOrTable` renderiza UM dos dois (cartão ou tabela) conforme
 * `useIsMobile`, então cada caso aqui declara em qual largura está: testar só o
 * desktop deixaria os cartões do celular sem cobertura nenhuma, e é neles que a
 * coluna de valor deixou de ficar fora da tela.
 */
const base: HistoryRow = {
  id: 1,
  settledAt: '2026-08-05T12:00:00Z',
  who: 'Você pagou Ana',
  billingMonth: '2026-07',
  note: 'Pix',
  amount: '40.00',
  currency: 'BRL',
  kind: 'sent',
};

function montar(rows: HistoryRow[], props: Partial<{ whoLabel: string }> = {}) {
  return render(
    <MemoryRouter>
      <SettlementHistory rows={rows} {...props} />
    </MemoryRouter>,
  );
}

/** `useIsMobile` lê `matchMedia`; o jsdom não o implementa. */
function larguraDe(mobile: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: mobile,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

describe('Histórico de acertos', () => {
  beforeEach(() => larguraDe(false));
  afterEach(() => vi.unstubAllGlobals());

  it('sem linha nenhuma, diz que não há acerto — e não desenha tabela vazia', () => {
    montar([]);
    expect(screen.getByText('Nenhum acerto registrado ainda.')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  /*
   * A pílula é a razão de o componente existir: `billing_month` sempre veio na
   * resposta e nunca aparecia, então o acerto que fecha um mês era
   * indistinguível do que só abate o acumulado (ADR 0031).
   */
  it('marca o mês que cada acerto fecha', () => {
    montar([base]);
    expect(screen.getByText('jul/2026')).toBeInTheDocument();
  });

  it('"sem mês" é um TIPO de acerto, não um campo vazio', () => {
    montar([{ ...base, billingMonth: null }]);
    expect(screen.getByText('sem mês')).toBeInTheDocument();
    // Um traço faria parecer dado faltando — e o que falta é justamente a
    // informação de que este acerto não fechou mês nenhum.
    expect(screen.queryByText('—')).not.toBeInTheDocument();
  });

  it('o valor segue a direção de quem olha', () => {
    montar([
      base,
      { ...base, id: 2, kind: 'received', amount: '25.00' },
      { ...base, id: 3, kind: 'neutral', amount: '10.00' },
    ]);
    expect(screen.getByText('−R$ 40,00').className).toContain('text-expense');
    expect(screen.getByText('+R$ 25,00').className).toContain('text-income');
    // Acerto entre terceiros não tem "para mim": nem sinal, nem cor de entrada.
    const terceiros = screen.getByText('R$ 10,00');
    expect(terceiros.className).toContain('text-foreground');
    expect(terceiros.textContent).not.toMatch(/^[+−]/);
  });

  it('a coluna de espaço só existe quando alguma linha tem espaço', () => {
    montar([base]);
    expect(screen.queryByRole('columnheader', { name: 'Espaço' })).not.toBeInTheDocument();

    montar([{ ...base, workspace: { id: 7, name: 'Viagem' } }]);
    expect(screen.getByRole('columnheader', { name: 'Espaço' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Viagem' })).toHaveAttribute('href', '/w/7/debts');
  });

  /*
   * Sem `onUndo` a coluna inteira some — é o caso da tela global, onde desfazer
   * mora na casa do acerto (a direção e o teto do ADR 0009 vivem lá).
   */
  it('desfazer só aparece quando a tela sabe desfazer', () => {
    montar([base]);
    expect(screen.queryByRole('button', { name: 'Desfazer acerto' })).not.toBeInTheDocument();

    const onUndo = vi.fn();
    montar([{ ...base, onUndo }]);
    fireEvent.click(screen.getByRole('button', { name: 'Desfazer acerto' }));
    expect(onUndo).toHaveBeenCalled();
  });

  it('sem permissão de escrita, o desfazer fica desabilitado (RBAC-FE-001)', () => {
    montar([{ ...base, onUndo: vi.fn(), canUndo: false }]);
    expect(screen.getByRole('button', { name: 'Desfazer acerto' })).toBeDisabled();
  });

  it('no celular vira cartão, com o mês e o valor à vista', () => {
    larguraDe(true);
    montar([{ ...base, workspace: { id: 7, name: 'Viagem' }, onUndo: vi.fn() }]);
    // Cartão, não tabela: a tabela vivia num rolamento horizontal e a coluna de
    // valor — a única que se foi ali ver — ficava fora da tela.
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.getByText('jul/2026')).toBeInTheDocument();
    expect(screen.getByText('−R$ 40,00')).toBeInTheDocument();
    expect(screen.getByText(/Viagem/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Desfazer/ })).toBeInTheDocument();
  });
});
