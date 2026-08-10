import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { OverviewPage } from '../OverviewPage';

/**
 * Visão global: competência × CAIXA (ADR 0022).
 *
 * A tela tinha 0% de cobertura — apontado pela auditoria externa — e é onde mora
 * a distinção que esta onda introduziu. O erro que ela precisa impedir é a volta
 * do colapso: um único número chamado "saída de caixa" que era, na verdade, a
 * soma dos pagadores dos lançamentos. São perguntas diferentes:
 *
 * - **Adiantado nos lançamentos** — o que assumi das despesas do mês. A compra
 *   no cartão entra aqui no ato, com o dinheiro ainda na conta.
 * - **Caixa** — o dinheiro que se moveu: fatura paga, acerto, parcela.
 *
 * O cenário abaixo é o que separa os dois de propósito: 300 assumidos nos
 * lançamentos e 1.000 de saída de caixa (uma fatura antiga paga neste mês). Se
 * alguém voltar a alimentar os dois campos com a mesma fonte, os números
 * colapsam e o teste cai.
 */
const OVERVIEW = {
  month: '2026-07',
  currency: 'BRL',
  income: '9000.00',
  consumption: '400.00',
  paid_in_transactions: '300.00',
  result: '8600.00',
  cash_in: '9000.00',
  cash_out: '1000.00',
  net_cash: '8000.00',
  cash_out_breakdown: {
    transactions: '300.00',
    statement_payments: '700.00',
    settlements_sent: '0.00',
    financing_installments: '0.00',
  },
  cash_in_breakdown: { income: '9000.00', settlements_received: '0.00' },
  to_pay: '0.00',
  to_receive: '100.00',
  by_workspace: [
    {
      workspace_id: 1,
      workspace_name: 'Casa',
      base_currency: 'BRL',
      consumption: '400.00',
      paid_in_transactions: '300.00',
      to_pay: '0.00',
      to_receive: '100.00',
    },
  ],
  excluded_foreign_count: 0,
};

const ATIVIDADE = [
  {
    id: 7,
    workspace_id: 1,
    workspace_name: 'Casa',
    title: 'Jantar',
    total_amount: '200.00',
    my_share: '100.00',
    currency: 'BRL',
    transaction_date: '2026-07-10T12:00:00Z',
    status: 'confirmed',
  },
];

// `vi.hoisted` porque a fábrica do `vi.mock` sobe para o topo do módulo e
// precisa do mock já existindo; o valor de retorno é definido no `beforeEach`,
// que corre depois das constantes deste arquivo.
const mockOverview = vi.hoisted(() => vi.fn());

vi.mock('@/hooks/use-overview', () => ({
  useOverview: (...args: unknown[]) => mockOverview(...args),
  useMyActivity: () => ({ activity: ATIVIDADE, isLoading: false }),
}));
vi.mock('@/hooks/use-auth', () => ({
  useAuth: () => ({ user: { id: 1, name: 'Gabriel Barros' } }),
}));

function renderOverview() {
  return render(
    <MemoryRouter>
      <OverviewPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  mockOverview.mockReturnValue({
    overview: OVERVIEW,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  });
});

describe('Visão global — competência e caixa são números diferentes', () => {
  /** O valor exibido por um tile, escopado ao próprio tile. */
  const valorDoTile = (rotulo: string) =>
    screen.getByText(rotulo).closest('div.rounded-xl')!.textContent ?? '';

  it('mostra o adiantado e o caixa lado a lado, com valores distintos', () => {
    renderOverview();
    expect(screen.getByText('Caixa do mês')).toBeInTheDocument();
    // 300 assumido ≠ 1.000 que saiu. Se voltarem a ser alimentados pela mesma
    // fonte — o defeito que o ADR 0022 corrigiu — os dois colapsam e isto cai.
    expect(valorDoTile('Adiantado nos lançamentos')).toMatch(/R\$\s*300,00/);
    expect(valorDoTile('Saiu')).toMatch(/R\$\s*1\.000,00/);
    expect(valorDoTile('Entrou')).toMatch(/R\$\s*9\.000,00/);
  });

  it('não chama mais de "saída de caixa" o que não é caixa', () => {
    renderOverview();
    expect(screen.queryByText('Saída de caixa')).not.toBeInTheDocument();
  });

  it('detalha de onde veio a saída — o total tem de ser conferível', () => {
    renderOverview();
    // Sem o detalhamento, "saiu R$ 1.000" não diz se a fatura entrou na conta.
    expect(screen.getByText('Faturas de cartão pagas')).toBeInTheDocument();
    expect(screen.getByText(/R\$\s*700,00/)).toBeInTheDocument();
    // Linhas zeradas não viram lista de zeros para quem não tem financiamento.
    expect(screen.queryByText('Parcelas de financiamento')).not.toBeInTheDocument();
  });

  it('resultado é renda menos CONSUMO, não menos caixa', () => {
    renderOverview();
    // 9.000 − 400 = 8.600. Se descontasse o caixa (1.000) daria 8.000, e quem
    // paga a conta do restaurante e é reembolsado ficaria no vermelho todo mês.
    const resultado = screen.getByText('Resultado do mês').closest('div.rounded-xl')!;
    expect(resultado.textContent).toMatch(/R\$\s*8\.600,00/);
  });
});

describe('Visão global — "Onde você está envolvido"', () => {
  it('mostra a MINHA parte em destaque, com o total como referência', () => {
    renderOverview();
    const secao = screen.getByText('Onde você está envolvido').closest('section')!;
    // A lista mostrava `total_amount`: num rateio 50/50, o jantar de 200
    // aparecia como 200 para quem consumiu 100.
    expect(within(secao).getByText(/R\$\s*100,00/)).toBeInTheDocument();
    expect(within(secao).getByText(/de\s*R\$\s*200,00/)).toBeInTheDocument();
  });
});

describe('Visão global — erro nunca vira um mês de zeros (Onda 9)', () => {
  it('falha da API mostra erro com retry, não "Renda R$ 0,00"', () => {
    // Sem o ramo de erro, `overview` chegava `undefined` e cada tile lia
    // `Number(undefined ?? 0)`: a tela afirmava um mês inteiro zerado, que é uma
    // resposta financeira — e era falsa (regra ERR-001).
    const refetch = vi.fn();
    mockOverview.mockReturnValue({
      overview: undefined, isLoading: false, isError: true, refetch,
    });
    render(
      <MemoryRouter>
        <OverviewPage />
      </MemoryRouter>,
    );

    expect(screen.getByText(/Não foi possível carregar a sua visão do mês/i)).toBeInTheDocument();
    expect(screen.queryByText('Renda')).not.toBeInTheDocument();
    expect(screen.queryByText('Resultado do mês')).not.toBeInTheDocument();
  });
});

describe('Visão global — drill-down das saídas', () => {
  it('o nome acessível do link inclui o rótulo E o valor', () => {
    // `aria-labelledby` SUBSTITUI o conteúdo como nome acessível; citando só o
    // <dt>, o link era anunciado como "Lançamentos à vista" e o valor — o dado
    // da linha — ficava de fora para quem usa leitor de tela.
    renderOverview();
    const secao = screen.getByText(/Clique em uma linha/i).closest('section')!;
    const links = within(secao).getAllByRole('link');
    expect(links.length).toBeGreaterThan(0);
    const nome = links[0].getAttribute('aria-labelledby') ?? '';
    // Dois ids: o do rótulo e o do valor.
    expect(nome.trim().split(/\s+/).length).toBe(2);
  });
});
