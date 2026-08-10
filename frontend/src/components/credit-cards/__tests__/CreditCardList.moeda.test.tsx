import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { CreditCardList } from '../CreditCardList';

/**
 * O prefixo do campo "Limite" tem de seguir a moeda ESCOLHIDA no formulário.
 *
 * O defeito que uma auditoria reproduziu no navegador: em "Novo cartão", trocar a
 * moeda para USD mudava o seletor mas deixava o campo Limite anunciando
 * `R$ 10.000,00`. O cartão nascia correto (`US$ 10.000,00` depois de criado), e é
 * justamente isso que tornava o erro traiçoeiro — a tela mostrava um número numa
 * moeda e gravava noutra, sem nenhum sinal de que tinham divergido.
 *
 * A causa era uma variável paralela ao estado: `dialogCurrency` derivava de
 * `editingId` e caía na moeda de RELATÓRIO durante a criação, ignorando o
 * `currency` que o seletor acabava de mudar. Duas fontes para o mesmo fato.
 */
const create = vi.fn();
const update = vi.fn();

vi.mock('@/hooks/use-credit-cards', () => ({
  useCreditCards: () => ({
    cards: [],
    isLoading: false,
    create,
    update,
    remove: vi.fn(),
  }),
}));
vi.mock('@/hooks/use-report-currency', () => ({ useReportCurrency: () => 'BRL' }));
vi.mock('@/components/ui/confirm', () => ({ useConfirm: () => vi.fn() }));

function abrirNovoCartao() {
  render(<CreditCardList />);
  // Há dois gatilhos com esse nome — o do cabeçalho e o do estado vazio —, e os
  // dois chamam `openCreate`. Qualquer um serve.
  fireEvent.click(screen.getAllByRole('button', { name: /novo cartão/i })[0]);
}

describe('CreditCardList — moeda do cartão no formulário', () => {
  beforeEach(() => {
    create.mockReset();
    create.mockResolvedValue({});
  });

  it('o campo Limite nasce na moeda de relatório', () => {
    abrirNovoCartao();
    expect(screen.getByText('R$')).toBeInTheDocument();
  });

  it('escolher USD troca o prefixo do Limite na hora', () => {
    abrirNovoCartao();

    fireEvent.click(screen.getByRole('button', { name: /moeda do cartão/i }));
    const lista = screen.getByRole('listbox');
    fireEvent.click(within(lista).getByRole('option', { name: /USD/ }));

    // O prefixo do MoneyInput, não só o rótulo do seletor: era ele que continuava
    // dizendo "R$" para um cartão que nasceria em dólar.
    expect(screen.getByText('US$')).toBeInTheDocument();
    expect(screen.queryByText('R$')).not.toBeInTheDocument();
  });

  it('a moeda escolhida é a que vai para o backend', async () => {
    abrirNovoCartao();

    fireEvent.change(screen.getByLabelText(/nome/i), { target: { value: 'Gringo' } });
    fireEvent.click(screen.getByRole('button', { name: /moeda do cartão/i }));
    const lista = screen.getByRole('listbox');
    fireEvent.click(within(lista).getByRole('option', { name: /USD/ }));
    fireEvent.change(screen.getByLabelText(/limite/i), { target: { value: '10000' } });
    fireEvent.click(screen.getByRole('button', { name: /criar cartão/i }));

    expect(create).toHaveBeenCalledWith(expect.objectContaining({ currency: 'USD' }));
  });

  it('o seletor de moeda é associado ao seu rótulo', () => {
    abrirNovoCartao();
    // `htmlFor="card-currency"` só chega à árvore de acessibilidade se o controle
    // carregar o `id`. Sem isso o leitor de tela anunciava só "Moeda".
    const botao = screen.getByRole('button', { name: /moeda do cartão/i });
    expect(botao).toHaveAttribute('id', 'card-currency');
  });
});
