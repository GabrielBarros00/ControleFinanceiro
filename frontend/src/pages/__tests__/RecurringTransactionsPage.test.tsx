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
  },
  {
    // Semanal: 55 por semana NÃO é 55 por mês. Se o total ignorar a frequência,
    // este item é o que denuncia.
    id: 3, title: 'Faxina', base_amount: '150.00', currency: 'BRL',
    frequency: 'weekly', interval: 1, day_of_month: 1, day_of_week: 2, is_active: true,
    category_id: null, payment_method: 'pix', credit_card_id: null,
  },
  {
    // Inativa: não sai dinheiro nenhum por ela, e somá-la infla o número.
    id: 4, title: 'Academia cancelada', base_amount: '99.00', currency: 'BRL',
    frequency: 'monthly', interval: 1, day_of_month: 8, is_active: false,
    category_id: null, payment_method: 'pix', credit_card_id: null,
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
vi.mock('@/hooks/use-credit-cards', () => ({ useCreditCards: () => ({ cards: [] }) }));
vi.mock('@/components/ui/confirm', () => ({ useConfirm: () => vi.fn() }));

const desenhar = () => render(<RecurringTransactionsPage />);

describe('Recorrência', () => {
  it('responde "quanto sai todo mês" somando as ativas na medida do mês', () => {
    desenhar();

    // 2500 + 55,90 (mensais) + 150 × (52/12) (semanal) = 3.205,90; a inativa fica de fora.
    const total = screen.getByTestId('total-mensal');
    expect(total).toHaveTextContent('3.205,90');
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

  it('ao editar, mostra quem já estava na divisão', async () => {
    desenhar();
    fireEvent.click(screen.getByRole('button', { name: /editar recorrência aluguel/i }));

    const dialogo = screen.getByRole('dialog');
    expect(within(dialogo).getByRole('button', { name: 'Ana' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(dialogo).getByRole('button', { name: 'Bruno' })).toHaveAttribute('aria-pressed', 'true');
  });
});
