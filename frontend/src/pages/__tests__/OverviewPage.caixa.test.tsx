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

/**
 * Saldo e projeção (ADR 0034) — o quarto eixo, e o que ele NÃO pode virar.
 *
 * Saldo (8.430,20) é um estoque; resultado do mês (8.600) é competência; caixa
 * do mês (8.000 líquidos) é movimento. Os três são números diferentes no mesmo
 * mês, e o cenário abaixo os mantém distintos de propósito: se alguém alimentar
 * dois deles da mesma fonte, os valores colapsam e o teste cai.
 */
const SALDO = {
  currency: 'BRL',
  total: '8430.20',
  accounts: [
    {
      account_id: 1, name: 'Nubank', type: 'checking', currency: 'BRL',
      active: true, is_default: true,
      opening_amount: '8000.00', opening_on: '2026-07-01',
      balance: '5930.20', movements_counted: 3,
    },
    {
      account_id: 2, name: 'Itaú', type: 'checking', currency: 'BRL',
      active: true, is_default: false,
      opening_amount: '2500.00', opening_on: '2026-07-01',
      balance: '2500.00', movements_counted: 0,
    },
  ],
  month: '2026-07',
  receivable_total: '6000.00',
  payable_total: '4380.00',
  projected_balance: '10050.20',
  breakdown: [
    { kind: 'income', label: 'Rendas a receber', amount: '6000.00', count: 1 },
    { kind: 'payables', label: 'Contas a pagar', amount: '2880.00', count: 4 },
    { kind: 'statements', label: 'Faturas de cartão', amount: '1500.00', count: 1 },
  ],
  unassigned_movements: 0,
  movements_before_opening: 0,
  accounts_without_opening: 0,
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
const mockBalance = vi.hoisted(() => vi.fn());

vi.mock('@/hooks/use-overview', () => ({
  useOverview: (...args: unknown[]) => mockOverview(...args),
  useMyActivity: () => ({ activity: ATIVIDADE, isLoading: false }),
}));
// O bloco de SALDO e PROJEÇÃO (ADR 0034) tem rota própria — mockada aqui pelo
// mesmo motivo do overview: este arquivo renderiza sem QueryClientProvider.
vi.mock('@/hooks/use-balance', () => ({
  useBalance: (...args: unknown[]) => mockBalance(...args),
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
  mockBalance.mockReturnValue({
    balance: SALDO,
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
    // "Resultado do mês" agora é o título da SEÇÃO de competência (ADR 0034); o
    // tile dentro dela se chama só "Resultado", para o mesmo nome não aparecer
    // duas vezes a 40px de distância.
    const resultado = screen.getByText('Resultado').closest('div.rounded-xl')!;
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


describe('Visão global — saldo e projeção (ADR 0034)', () => {
  it('mostra o saldo por conta: "onde está o meu dinheiro" é pergunta própria', () => {
    renderOverview();
    const secao = screen.getByRole('heading', { name: 'Seu dinheiro' }).closest('section')!;
    expect(within(secao).getByText('R$ 8.430,20')).toBeInTheDocument();
    expect(within(secao).getByText('Nubank')).toBeInTheDocument();
    expect(within(secao).getByText('R$ 5.930,20')).toBeInTheDocument();
    expect(within(secao).getByText('Itaú')).toBeInTheDocument();
  });

  it('saldo, resultado e caixa são TRÊS números diferentes no mesmo mês', () => {
    renderOverview();
    // Se alguém voltar a alimentar dois deles da mesma fonte, os valores
    // colapsam — é exatamente o defeito que o ADR 0022 já corrigiu uma vez.
    // O saldo aparece duas vezes de propósito (o total e o ponto de partida da
    // projeção); o que importa é que os TRÊS números sejam diferentes.
    expect(screen.getAllByText('R$ 8.430,20').length).toBeGreaterThan(0); // saldo
    expect(screen.getByText('+R$ 8.600,00')).toBeInTheDocument(); // resultado
    expect(screen.getByText('+R$ 8.000,00')).toBeInTheDocument(); // caixa líquido
  });

  it('a projeção é saldo atual + a receber − a pagar, com o detalhe de onde vem', () => {
    renderOverview();
    const secao = screen.getByRole('heading', { name: 'Até o fim do mês' }).closest('section')!;
    // "a receber" aparece no tile E na linha de detalhe — as duas de propósito.
    expect(within(secao).getAllByText('+R$ 6.000,00').length).toBeGreaterThan(0);
    expect(within(secao).getByText('−R$ 4.380,00')).toBeInTheDocument();
    expect(within(secao).getByText('+R$ 10.050,20')).toBeInTheDocument();
    // Sem o detalhe, "a pagar 4.380" não é conferível: a pessoa não teria como
    // saber se a fatura do cartão entrou na conta.
    expect(within(secao).getByText('Faturas de cartão')).toBeInTheDocument();
  });

  it('conta sem saldo configurado PEDE o número em vez de mostrar zero', () => {
    mockBalance.mockReturnValue({
      balance: { ...SALDO, total: null, projected_balance: null, accounts_without_opening: 2 },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    renderOverview();
    // Zero é um valor errado apresentado com a confiança de um certo — e a
    // migração não inventa saldo nenhum (§6 do pedido).
    expect(screen.getByText('Saldo ainda não configurado')).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: /Informar saldo das contas/ }),
    ).toBeInTheDocument();
    // E o tile da projeção NÃO pode dizer "R$ 0,00": um zero ali é uma resposta,
    // e uma resposta falsa. "Não sei quanto você tem" ≠ "você não tem nada".
    const projecao = screen
      .getByRole('heading', { name: 'Até o fim do mês' })
      .closest('section')!;
    expect(within(projecao).queryByText('R$ 0,00')).not.toBeInTheDocument();
    expect(within(projecao).getAllByText('—').length).toBe(2);
  });
});
