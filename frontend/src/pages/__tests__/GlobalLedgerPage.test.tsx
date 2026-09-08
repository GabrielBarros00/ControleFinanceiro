import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { GlobalLedgerPage } from '../GlobalLedgerPage';

/**
 * Extrato global.
 *
 * A razão de existir: a Visão global dizia "saiu R$ 4.200" e mostrava a origem,
 * mas não havia como chegar às LINHAS. Aqui elas aparecem — com a data efetiva
 * (ADR 0022), a origem, o workspace e, quando o movimento foi em outra moeda, o
 * valor original ao lado do convertido.
 */
const LEDGER = {
  currency: 'BRL',
  month: '2026-07',
  total: 3,
  cash_in: '5000.00',
  cash_out: '420.00',
  net_cash: '4580.00',
  excluded_foreign_count: 0,
  entries: [
    {
      source: 'income', direction: 'in', occurred_on: '2026-07-20',
      amount: '5000.00', currency: 'BRL', converted_amount: '5000.00',
      title: 'Salário', workspace_id: null, workspace_name: null,
      card_id: null, financing_id: null, counterparty_id: null,
      counterparty_name: null, reference_id: 1,
    },
    {
      source: 'statement_payment', direction: 'out', occurred_on: '2026-07-15',
      amount: '300.00', currency: 'BRL', converted_amount: '300.00',
      title: 'Nubank — fatura de 2026-07', workspace_id: null, workspace_name: null,
      card_id: 9, financing_id: null, counterparty_id: null,
      counterparty_name: null, reference_id: 2,
    },
    {
      source: 'settlement_sent', direction: 'out', occurred_on: '2026-07-10',
      amount: '120.00', currency: 'BRL', converted_amount: '120.00',
      title: 'Acerto enviado', workspace_id: 1, workspace_name: 'Casa',
      card_id: null, financing_id: null, counterparty_id: 2,
      counterparty_name: 'Vizinho', reference_id: 3,
    },
  ],
};

const SEM_COTACAO = {
  ...LEDGER,
  excluded_foreign_count: 1,
  entries: [
    {
      ...LEDGER.entries[1],
      amount: '100.00', currency: 'USD', converted_amount: null,
    },
  ],
};

const mockLedger = vi.fn();
vi.mock('@/hooks/use-overview', () => ({
  useLedger: (...args: unknown[]) => mockLedger(...args),
}));
vi.mock('@/hooks/use-workspaces', () => ({
  useWorkspaces: () => ({ workspaces: [{ id: 1, name: 'Casa' }, { id: 2, name: 'Viagem' }] }),
}));
vi.mock('@/hooks/use-credit-cards', () => ({
  useCreditCards: () => ({
    cards: [
      { id: 9, name: 'Nubank', currency: 'BRL' },
      { id: 10, name: 'Inter', currency: 'BRL' },
    ],
  }),
}));

function renderPage(
  ledger: unknown = LEDGER,
  rota = '/me/ledger?month=2026-07',
  extra: { isError?: boolean; refetch?: () => void } = {},
) {
  mockLedger.mockReturnValue({
    ledger,
    isLoading: false,
    isError: extra.isError ?? false,
    refetch: extra.refetch ?? vi.fn(),
  });
  return render(
    <MemoryRouter initialEntries={[rota]}>
      <GlobalLedgerPage />
    </MemoryRouter>,
  );
}

describe('Extrato global', () => {
  beforeEach(() => mockLedger.mockReset());

  it('lista os movimentos com data, origem e contraparte', () => {
    renderPage();
    expect(screen.getByText('Salário')).toBeInTheDocument();
    expect(screen.getByText('Nubank — fatura de 2026-07')).toBeInTheDocument();
    expect(screen.getByText('· Vizinho')).toBeInTheDocument();
    // "Casa" está na tabela E na <option> do filtro — escopa na tabela.
    const tabela = screen.getByRole('table');
    expect(within(tabela).getByText('Casa')).toBeInTheDocument();
    expect(within(tabela).getByText('Rendas')).toBeInTheDocument();
  });

  it('mostra entrada, saída e saldo do mês', () => {
    renderPage();
    expect(screen.getByText('Entrou')).toBeInTheDocument();
    expect(screen.getByText('Saiu')).toBeInTheDocument();
    expect(screen.getByText('Saldo do mês')).toBeInTheDocument();
  });

  it('mostra que nada está filtrado em vez de deixar seis chips apagados', () => {
    renderPage();
    // Sem filtro, "Todas" é o chip aceso: a tela AFIRMA que está mostrando tudo.
    expect(screen.getByRole('button', { name: 'Todas' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Rendas' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('apaga "Todas" quando um recorte entra', () => {
    renderPage(LEDGER, '/me/ledger?month=2026-07&source=income');
    expect(screen.getByRole('button', { name: 'Todas' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('lê o filtro de origem da URL e o repassa ao hook', () => {
    renderPage(LEDGER, '/me/ledger?month=2026-07&source=income');
    expect(mockLedger).toHaveBeenCalledWith(
      expect.objectContaining({ source: ['income'], month: '2026-07' }),
    );
    expect(screen.getByRole('button', { name: 'Rendas' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('alternar uma origem muda o recorte', () => {
    renderPage();
    expect(screen.getByRole('button', { name: 'Faturas' })).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(screen.getByRole('button', { name: 'Faturas' }));
    expect(screen.getByRole('button', { name: 'Faturas' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('filtra por workspace quando há mais de um', () => {
    renderPage();
    const seletor = screen.getByLabelText('Filtrar por espaço');
    fireEvent.change(seletor, { target: { value: '2' } });
    expect(mockLedger).toHaveBeenLastCalledWith(
      expect.objectContaining({ workspace_id: 2 }),
    );
  });

  it('movimento sem cotação aparece MARCADO, não some nem vira zero', () => {
    renderPage(SEM_COTACAO);
    // A política do ADR 0006: omitir da soma, mas mostrar e contar.
    expect(screen.getByTitle('Sem cotação para esta data')).toBeInTheDocument();
  });

  it('mês vazio explica que não houve movimento', () => {
    renderPage({ ...LEDGER, entries: [], total: 0 });
    expect(screen.getByText('Nenhum movimento neste recorte')).toBeInTheDocument();
  });

  it('com filtro ativo, o vazio sugere limpá-lo', () => {
    renderPage({ ...LEDGER, entries: [], total: 0 }, '/me/ledger?source=income');
    expect(screen.getByText(/Limpe-os para ver o mês inteiro/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Limpar filtros' })).toBeInTheDocument();
  });

  it('filtra por cartão quando há mais de um', () => {
    renderPage();
    fireEvent.change(screen.getByLabelText('Filtrar por cartão'), { target: { value: '9' } });
    expect(mockLedger).toHaveBeenLastCalledWith(
      expect.objectContaining({ card_id: 9 }),
    );
  });
});

/**
 * Paginação.
 *
 * A tela fixava `limit: 200` e, passando disso, mandava "use os filtros para
 * estreitar o recorte" — que não é resposta para quem tem mais de 200
 * movimentos no mês: o resto do extrato ficava inalcançável. O backend sempre
 * aceitou `limit`/`offset`.
 */
describe('Extrato global — paginação', () => {
  beforeEach(() => mockLedger.mockReset());

  const MUITOS = { ...LEDGER, total: 312 };

  it('pede a primeira página com limite e offset', () => {
    renderPage(MUITOS);
    expect(mockLedger).toHaveBeenCalledWith(
      expect.objectContaining({ limit: 100, offset: 0 }),
    );
  });

  it('mostra o intervalo e o total, não só "mostrando N de M"', () => {
    renderPage(MUITOS);
    expect(screen.getByText(/Mostrando 1–3 de 312 movimentos/)).toBeInTheDocument();
  });

  it('a página vem da URL — o recorte é compartilhável', () => {
    renderPage(MUITOS, '/me/ledger?month=2026-07&page=2');
    expect(mockLedger).toHaveBeenCalledWith(
      expect.objectContaining({ offset: 200 }),
    );
    expect(screen.getByText(/Mostrando 201–203 de 312/)).toBeInTheDocument();
  });

  it('"Anterior" fica desabilitado na primeira página', () => {
    renderPage(MUITOS);
    expect(screen.getByRole('button', { name: 'Anterior' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Próxima' })).toBeEnabled();
  });

  it('"Próxima" fica desabilitado na última página', () => {
    renderPage(MUITOS, '/me/ledger?month=2026-07&page=3');
    expect(screen.getByRole('button', { name: 'Próxima' })).toBeDisabled();
  });

  it('avançar muda o offset pedido', () => {
    renderPage(MUITOS);
    fireEvent.click(screen.getByRole('button', { name: 'Próxima' }));
    expect(mockLedger).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 100 }),
    );
  });

  it('trocar de filtro volta para a primeira página', () => {
    renderPage(MUITOS, '/me/ledger?month=2026-07&page=2');
    fireEvent.click(screen.getByRole('button', { name: 'Faturas' }));
    expect(mockLedger).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 0 }),
    );
  });

  it('cabendo numa página, não há paginador', () => {
    renderPage(LEDGER);
    expect(screen.queryByRole('button', { name: 'Próxima' })).not.toBeInTheDocument();
  });

  // --- Erro nunca pode parecer "mês vazio" (Onda 9) ------------------------

  it('falha da API vira erro com retry, não um mês zerado', () => {
    // O defeito: `useLedger` descartava `isError`, então uma falha chegava como
    // `ledger === undefined` e os StatTile liam `Number(undefined ?? 0)`. A tela
    // anunciava "Entrou R$ 0,00 / Saiu R$ 0,00" — uma afirmação financeira que
    // não tinha como ser verdadeira, porque nada foi calculado.
    const refetch = vi.fn();
    renderPage(undefined, '/me/ledger?month=2026-07', { isError: true, refetch });

    expect(screen.getByText(/Não foi possível carregar o extrato/i)).toBeInTheDocument();
    expect(screen.queryByText('Nada entrou nem saiu neste mês.')).not.toBeInTheDocument();
    expect(screen.queryByText('Entrou')).not.toBeInTheDocument();
  });

  it('id inválido na URL não vira requisição', () => {
    // `?workspace_id=abc` virava `Number('abc')` = NaN, viajava como
    // `workspace_id=NaN`, a API respondia 422 — e a tela culpava o filtro,
    // dizendo "nenhum movimento com estes filtros".
    renderPage(LEDGER, '/me/ledger?month=2026-07&workspace_id=abc');
    expect(mockLedger).toHaveBeenLastCalledWith(
      expect.objectContaining({ workspace_id: undefined }),
    );
  });

  it('id fracionário na URL é descartado como qualquer outro lixo', () => {
    // `Number.isFinite(1.5)` é `true`, então `?workspace_id=1.5` passava pela
    // validação, viajava inteiro e a API devolvia 422 — o mesmo beco do `abc`,
    // por um valor que a tela podia ter descartado sozinha. Id é chave primária.
    renderPage(LEDGER, '/me/ledger?month=2026-07&workspace_id=1.5&card_id=2.7');
    expect(mockLedger).toHaveBeenLastCalledWith(
      expect.objectContaining({ workspace_id: undefined, card_id: undefined }),
    );
  });

  it('página fracionária não vira um offset que ninguém pediu', () => {
    // `?page=1.5` × 100 por página = `offset=150`, um recorte no meio de uma
    // página que a tela então anunciava como "esta página não existe".
    renderPage(LEDGER, '/me/ledger?month=2026-07&page=1.5');
    expect(mockLedger).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 100 }),
    );
  });

  it.each(['Infinity', '-Infinity', '1e400', 'abc', '-3'])(
    'página impossível (%s) cai na primeira, em vez de um offset que a API recusa',
    (valor) => {
      // O furo que sobrava era o infinito: `Math.floor(Infinity)` é `Infinity`,
      // e ele viajava literalmente como `offset=Infinity` na query string. A API
      // respondia 422 e a tela dizia "não foi possível carregar o extrato" — um
      // erro de rede para um valor que ela mesma podia ter descartado.
      // `1e400` é o mesmo caso por outro caminho: `Number('1e400')` é `Infinity`.
      renderPage(LEDGER, `/me/ledger?month=2026-07&page=${valor}`);
      expect(mockLedger).toHaveBeenLastCalledWith(
        expect.objectContaining({ offset: 0 }),
      );
    },
  );

  it('página fora do intervalo oferece a volta, em vez de um beco sem saída', () => {
    // `?page=999` dizia "nada entrou nem saiu neste mês" — falso, e sem
    // paginação para voltar, porque ela só é desenhada quando há linhas.
    renderPage({ ...LEDGER, total: 3, entries: [] }, '/me/ledger?month=2026-07&page=999');

    expect(screen.getByText('Esta página não existe')).toBeInTheDocument();
    expect(screen.queryByText('Nada entrou nem saiu neste mês.')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /primeira página/i }));
    expect(mockLedger).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 0 }),
    );
  });
});
