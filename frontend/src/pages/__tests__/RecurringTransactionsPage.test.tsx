import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@/test/utils';
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

vi.mock('@/hooks/use-recurring', () => ({
  useRecurring: () => ({
    recurring: ITENS,
    isLoading: false,
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    generate: vi.fn(),
    preview: vi.fn(),
    isGenerating: false,
    isPreviewing: false,
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
