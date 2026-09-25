import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within, fireEvent, waitFor } from '@/test/utils';
import { RecurringTransactionsPage } from '../RecurringTransactionsPage';

/**
 * Recorrência — a tela que sabia tudo menos a resposta.
 *
 * Ela lista aluguel, assinaturas e mensalidades, cada um com valor, frequência e
 * status. E a pergunta que leva alguém até aqui é uma só: **quanto sai todo mês,
 * fixo, antes de eu gastar qualquer coisa?** Esse número não existia em lugar
 * nenhum — dava para somar de cabeça, o que é o mesmo que dizer que a tela
 * entrega dados e cobra a conta do usuário.
 *
 * O outro achado é de ruído, não de falta: uma coluna "Status" cujo valor é
 * "Ativo" em toda linha (quem desativa some da lista mental de quem lê) e uma
 * coluna "Ações" que aparece vazia porque os botões só surgem no `hover` — num
 * `<table>` de desktop, onde o ponteiro está num lugar só.
 */
const ITENS = [
  {
    id: 1, title: 'Aluguel', base_amount: '2500.00', currency: 'BRL',
    frequency: 'monthly', interval: 1, day_of_month: 5, is_active: true,
    category_id: null, payment_method: 'pix', credit_card_id: null,
    // O equivalente mensal vem do servidor (ADR 0039), como a API manda.
    monthly_equivalent: '2500.00', my_monthly_equivalent: '1250.00',
    // Já dividido: é o que o teste de edição carrega de volta nas pílulas.
    split_snapshot: [
      { user_id: 1, split_method: 'equal', input_value: '0' },
      { user_id: 2, split_method: 'equal', input_value: '0' },
    ],
  },
  {
    id: 2, title: 'Streaming', base_amount: '55.90', currency: 'BRL',
    frequency: 'monthly', interval: 1, day_of_month: 12, is_active: true,
    category_id: null, payment_method: 'credit_card', credit_card_id: null,
    monthly_equivalent: '55.90', my_monthly_equivalent: '55.90',
    is_subscription: true, plan: 'Premium', next_occurrence: '2099-01-12',
  },
  {
    // Semanal: 55 por semana NÃO é 55 por mês. Se o total ignorar a frequência,
    // este item é o que denuncia.
    id: 3, title: 'Faxina', base_amount: '150.00', currency: 'BRL',
    frequency: 'weekly', interval: 1, day_of_month: 1, day_of_week: 2, is_active: true,
    category_id: null, payment_method: 'pix', credit_card_id: null,
    monthly_equivalent: '650.00', my_monthly_equivalent: '650.00',
  },
  {
    // Inativa: não sai dinheiro nenhum por ela, e somá-la infla o número.
    id: 4, title: 'Academia cancelada', base_amount: '99.00', currency: 'BRL',
    frequency: 'monthly', interval: 1, day_of_month: 8, is_active: false,
    category_id: null, payment_method: 'pix', credit_card_id: null,
    monthly_equivalent: '99.00', my_monthly_equivalent: '99.00', is_subscription: true,
  },
];

const criar = vi.hoisted(() => vi.fn());
vi.mock('@/hooks/use-recurring', () => ({
  useRecurring: () => ({
    recurring: ITENS,
    isLoading: false,
    create: criar,
    update: vi.fn(),
    remove: vi.fn(),
    generate: vi.fn(),
    preview: vi.fn(),
    isGenerating: false,
    isPreviewing: false,
  }),
}));
vi.mock('@/hooks/use-members', () => ({
  useMembers: () => ({
    members: [
      { user_id: 1, user_name: 'Ana' },
      { user_id: 2, user_name: 'Bruno' },
    ],
    memberName: (id: number) => (id === 1 ? 'Ana' : 'Bruno'),
  }),
}));
vi.mock('@/hooks/use-categories', () => ({
  useCategories: () => ({ categories: [], categoryName: () => 'Sem categoria' }),
}));
vi.mock('@/hooks/use-base-currency', () => ({ useBaseCurrency: () => 'BRL' }));
vi.mock('@/hooks/use-credit-cards', () => ({
  useCreditCards: () => ({ cards: [{ id: 9, name: 'Nubank', currency: 'BRL' }] }),
}));
vi.mock('@/components/ui/confirm', () => ({ useConfirm: () => vi.fn() }));

const desenhar = () => render(<RecurringTransactionsPage />);

describe('Recorrência', () => {
  it('responde "quanto sai todo mês" somando as ativas na medida do mês', () => {
    desenhar();

    // 2500 + 55,90 (mensais) + 150 × (52/12) (semanal) = 3.205,90; a inativa fica de fora.
    const total = screen.getByTestId('total-mensal');
    expect(total).toHaveTextContent('3.205,90');
  });

  it('assinaturas: quadro com a sua parte por mês, selo e o recorte "Só assinaturas"', () => {
    desenhar();
    const quadro = screen.getByTestId('quadro-assinaturas');
    // Só a ativa: a academia cancelada é assinatura, mas não cobra.
    expect(quadro).toHaveTextContent('55,90');
    expect(quadro).toHaveTextContent('Premium');
    expect(quadro).not.toHaveTextContent('Academia');
    const tabela = screen.getByRole('table');
    expect(within(tabela).getAllByText(/^Assinatura/)).toHaveLength(2);
    fireEvent.click(screen.getByRole('button', { name: 'Só assinaturas' }));
    expect(within(screen.getByRole('table')).queryByText('Aluguel')).toBeNull();
    expect(within(screen.getByRole('table')).getByText('Streaming')).toBeInTheDocument();
  });

  it('não conta a recorrência desativada no total', () => {
    desenhar();
    // Controle do teste acima: se a inativa entrasse, o total seria 3.304,90.
    expect(screen.getByTestId('total-mensal')).not.toHaveTextContent('3.304,90');
  });

  it('marca a recorrência inativa na própria linha, sem uma coluna só para isso', () => {
    desenhar();

    const tabela = screen.getByRole('table');
    // A informação continua na tela...
    expect(within(tabela).getByText(/inativa/i)).toBeInTheDocument();
    // ...mas sem uma coluna cujo cabeçalho promete algo que quase toda linha
    // responde igual.
    expect(within(tabela).queryByRole('columnheader', { name: /status/i })).toBeNull();
  });

  it('mostra as ações sem depender do ponteiro', () => {
    desenhar();

    const tabela = screen.getByRole('table');
    const editar = within(tabela).getByRole('button', { name: /editar recorrência aluguel/i });
    // `opacity-0` deixa o botão no DOM e invisível: a coluna "Ações" fica com
    // cabeçalho e nada embaixo até o ponteiro passar. Em tela de toque, nunca.
    expect(editar.parentElement?.className ?? '').not.toMatch(/opacity-0/);
  });
});

/**
 * "Dividir com" na recorrência.
 *
 * O aluguel dividido em três é uma despesa fixa por definição — ela se repete
 * todo mês, com as mesmas pessoas. Mas a recorrência era o único lugar do app
 * onde não dava para dizer isso: cada ocorrência nascia 100% de quem cadastrou,
 * e a divisão tinha de ser refeita À MÃO em toda instância materializada. Como a
 * materialização é preguiçosa, a ocorrência do mês seguinte nascia errada de
 * novo, sozinha, quando alguém abrisse uma tela de leitura.
 *
 * O backend já sabia dividir desde o ADR 0012 (`split_snapshot` no template,
 * convertido em `TransactionSplit` de verdade a cada ocorrência, com teste em
 * `test_recurring_snapshot.py`). O que faltava era a tela perguntar.
 */
describe('Recorrência — dividir com', () => {
  // Sem isto, `calls[0]` é a chamada do teste ANTERIOR — e o teste do caso
  // vazio lia a divisão montada duas asserções acima.
  beforeEach(() => criar.mockClear());

  const abrirFormulario = async () => {
    desenhar();
    fireEvent.click(screen.getByRole('button', { name: /nova despesa/i }));
    return screen.getByRole('dialog');
  };

  it('oferece os membros do espaço para dividir', async () => {
    const dialogo = await abrirFormulario();
    expect(within(dialogo).getByText('Dividir com')).toBeInTheDocument();
    expect(within(dialogo).getByRole('button', { name: 'Ana' })).toBeInTheDocument();
    expect(within(dialogo).getByRole('button', { name: 'Bruno' })).toBeInTheDocument();
  });

  it('manda a divisão no snapshot do template', async () => {
    const dialogo = await abrirFormulario();
    fireEvent.change(within(dialogo).getByLabelText(/título/i), {
      target: { value: 'Aluguel' },
    });
    fireEvent.change(within(dialogo).getByLabelText(/valor/i), {
      target: { value: '3.000,00' },
    });
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Ana' }));
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Bruno' }));
    fireEvent.click(within(dialogo).getByRole('button', { name: /salvar/i }));

    await waitFor(() => expect(criar).toHaveBeenCalled());
    // O hook recebe `{ data, ... }`: o payload da recorrência vai dentro.
    expect(criar.mock.calls[0][0].data).toMatchObject({
      split_snapshot: [
        { user_id: 1, split_method: 'equal', input_value: 0 },
        { user_id: 2, split_method: 'equal', input_value: 0 },
      ],
    });
  });

  it('sem ninguém marcado, não manda divisão nenhuma', async () => {
    // Contrapeso: o padrão continua sendo "100% de quem cadastrou". Mandar uma
    // lista vazia seria diferente de não mandar — o backend trata `None` como
    // "sem divisão declarada" e `[]` viraria uma despesa sem dono.
    const dialogo = await abrirFormulario();
    fireEvent.change(within(dialogo).getByLabelText(/título/i), {
      target: { value: 'Internet' },
    });
    fireEvent.change(within(dialogo).getByLabelText(/valor/i), {
      target: { value: '120,00' },
    });
    fireEvent.click(within(dialogo).getByRole('button', { name: /salvar/i }));

    await waitFor(() => expect(criar).toHaveBeenCalled());
    expect(criar.mock.calls[0][0].data.split_snapshot).toBeNull();
  });

  it('assinatura: manda plano, teste, benefícios e o estabelecimento', async () => {
    const dialogo = await abrirFormulario();
    fireEvent.change(within(dialogo).getByLabelText(/título/i), { target: { value: 'Netflix' } });
    fireEvent.change(within(dialogo).getByLabelText(/valor/i), { target: { value: '55,90' } });
    fireEvent.change(within(dialogo).getByLabelText(/estabelecimento/i), { target: { value: 'Netflix' } });
    fireEvent.click(within(dialogo).getByRole('switch', { name: /é uma assinatura/i }));
    fireEvent.change(within(dialogo).getByLabelText('Plano'), { target: { value: 'Premium' } });
    fireEvent.change(within(dialogo).getByLabelText('Teste grátis até'), { target: { value: '2099-01-10' } });
    fireEvent.change(within(dialogo).getByLabelText('Benefícios'), { target: { value: '4 telas' } });
    fireEvent.click(within(dialogo).getByRole('button', { name: /salvar/i }));
    await waitFor(() => expect(criar).toHaveBeenCalled());
    expect(criar.mock.calls[0][0].data).toMatchObject({
      is_subscription: true, plan: 'Premium', trial_ends_on: '2099-01-10', notes: '4 telas', merchant_name: 'Netflix',
    });
  });

  it('sem assinatura nem estabelecimento, não manda plano nem vínculo', async () => {
    const dialogo = await abrirFormulario();
    fireEvent.change(within(dialogo).getByLabelText(/título/i), { target: { value: 'Internet' } });
    fireEvent.change(within(dialogo).getByLabelText(/valor/i), { target: { value: '120,00' } });
    fireEvent.click(within(dialogo).getByRole('button', { name: /salvar/i }));
    await waitFor(() => expect(criar).toHaveBeenCalled());
    const corpo = criar.mock.calls[0][0].data;
    expect(corpo).toMatchObject({ is_subscription: false, plan: null, trial_ends_on: null, notes: null });
    // Vazio na criação: o servidor liga pelo apelido do título.
    expect('merchant_name' in corpo || 'merchant_id' in corpo).toBe(false);
  });

  it('ao editar, mostra quem já estava na divisão', async () => {
    desenhar();
    fireEvent.click(screen.getByRole('button', { name: /editar recorrência aluguel/i }));

    const dialogo = screen.getByRole('dialog');
    expect(within(dialogo).getByRole('button', { name: 'Ana' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(dialogo).getByRole('button', { name: 'Bruno' })).toHaveAttribute('aria-pressed', 'true');
  });
});

/**
 * "No cartão" sem cartão.
 *
 * O backend recusa (a ocorrência materializada nasceria num estado que a rota
 * de despesa proíbe: diz-se no cartão, não entra em fatura nenhuma e ainda cai
 * em Contas a pagar). Mas o formulário oferecia "Sem cartão" como opção e só
 * descobria no submit — e o erro do servidor chega depois de a pessoa achar que
 * terminou.
 *
 * O achado é de uma varredura de telas com a base cheia: "Contas a pagar"
 * listando uma despesa etiquetada "Cartão de crédito".
 */
describe('Recorrência — cartão coerente', () => {
  const abrir = () => {
    desenhar();
    fireEvent.click(screen.getByRole('button', { name: /nova despesa/i }));
    return screen.getByRole('dialog');
  };

  it('avisa e trava o salvar quando o crédito fica sem cartão', () => {
    const dialogo = abrir();
    fireEvent.change(within(dialogo).getByLabelText(/forma de pagamento/i), {
      target: { value: 'credit_card' },
    });

    expect(within(dialogo).getByText(/escolha o cartão/i)).toBeInTheDocument();
    expect(within(dialogo).getByRole('button', { name: /^salvar$/i })).toBeDisabled();
  });

  it('destrava ao escolher o cartão', () => {
    const dialogo = abrir();
    fireEvent.change(within(dialogo).getByLabelText(/forma de pagamento/i), {
      target: { value: 'credit_card' },
    });
    fireEvent.change(within(dialogo).getByLabelText(/qual cartão/i), {
      target: { value: '9' },
    });

    expect(within(dialogo).queryByText(/escolha o cartão/i)).toBeNull();
    expect(within(dialogo).getByRole('button', { name: /^salvar$/i })).toBeEnabled();
  });

  it('outro método não pede cartão nenhum', () => {
    // Contrapeso: travar sempre seria pior que o defeito.
    const dialogo = abrir();
    fireEvent.change(within(dialogo).getByLabelText(/forma de pagamento/i), {
      target: { value: 'pix' },
    });
    expect(within(dialogo).getByRole('button', { name: /^salvar$/i })).toBeEnabled();
  });
});
