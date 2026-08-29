import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { PayablesList } from '../PayablesList';
import type { Payables } from '@/hooks/use-payables';

/**
 * Contas a pagar (ADR 0029) — a fila do que ainda não saiu do caixa.
 *
 * O erro que estes testes impedem é o mais caro que uma tela de obrigações pode
 * cometer: **mandar a conta para o espaço errado**. A lista pessoal mistura
 * casas, e a escrita é POR espaço; sem agrupar a seleção por `workspace_id`, o
 * clique manda os ids de duas casas para a rota de uma só. O servidor responde
 * 200 com `updated: 0` — não há erro, não há toast vermelho, e a linha continua
 * exatamente onde estava.
 */
const CONTAS: Payables = {
  currency: 'BRL',
  month: '2026-08',
  total: '1500.00',
  overdue_total: '300.00',
  due_this_month_total: '1200.00',
  entries: [
    {
      transaction_id: 10,
      workspace_id: 1,
      workspace_name: 'Casa',
      title: 'Luz',
      due_date: '2026-08-05',
      billing_month: '2026-08',
      amount: '300.00',
      currency: 'BRL',
      converted_amount: '300.00',
      payment_method: 'boleto',
      is_overdue: true,
      recurring_expense_id: 4,
      installment_no: null,
      installments_of: null,
      from_past_month: false,
    },
    {
      transaction_id: 20,
      workspace_id: 2,
      workspace_name: 'Viagem',
      title: 'Pousada',
      due_date: '2026-08-28',
      billing_month: '2026-08',
      amount: '1200.00',
      currency: 'BRL',
      converted_amount: '1200.00',
      payment_method: 'pix',
      is_overdue: false,
      recurring_expense_id: null,
      installment_no: null,
      installments_of: null,
      from_past_month: false,
    },
  ],
  excluded_foreign_count: 0,
};

const mockSettle = vi.hoisted(() => vi.fn());

vi.mock('@/hooks/use-payables', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  useSettlePayables: () => ({ settle: mockSettle, isSettling: false }),
}));

function renderLista(props: Partial<Parameters<typeof PayablesList>[0]> = {}) {
  return render(
    <PayablesList
      payables={CONTAS}
      isLoading={false}
      isError={false}
      onRetry={vi.fn()}
      showWorkspace
      {...props}
    />,
  );
}

beforeEach(() => {
  mockSettle.mockReset();
  mockSettle.mockResolvedValue({ status: 'ok', updated: 1, skipped: 0 });
});

describe('Contas a pagar — a fila', () => {
  it('separa vencidas do resto: uma fila de pagamento se lê por urgência', () => {
    renderLista();
    expect(screen.getByText('Vencidas')).toBeInTheDocument();
    expect(screen.getByText('A vencer')).toBeInTheDocument();
    expect(screen.getByText('vencida')).toBeInTheDocument();
  });

  it('marca a conta que veio de recorrência', () => {
    // Saber que a linha é automática muda o que se faz com ela: confirmar o
    // pagamento, ou ir atrás de quem deveria ter pago.
    renderLista();
    expect(screen.getByText('fixa')).toBeInTheDocument();
  });

  it('mostra o espaço na camada pessoal e o esconde na do espaço', () => {
    const { unmount } = renderLista();
    expect(screen.getByText(/Casa/)).toBeInTheDocument();
    unmount();

    renderLista({ showWorkspace: false });
    // Sem o nome do espaço, duas contas de "Aluguel" seriam indistinguíveis —
    // mas dentro de UMA casa ele é ruído repetido em toda linha.
    expect(screen.queryByText(/·\s*Casa/)).not.toBeInTheDocument();
  });

  /*
   * O total das duas camadas sai da mesma consulta, mas não é o mesmo número: a
   * pessoal soma o meu `TransactionPayer`, a do espaço soma os pagadores todos
   * (`_por_lancamento`). As duas telas mostravam "Sai do caixa quando VOCÊ
   * marcar como pago" sobre valores de donos diferentes — e no espaço isso é
   * falso para toda conta que outra pessoa vai pagar.
   */
  it('diz de quem é o caixa que o total representa', () => {
    const { unmount } = renderLista();
    expect(screen.getByText('O que você assumiu e ainda não pagou')).toBeInTheDocument();
    unmount();

    renderLista({ escopo: 'espaco', showWorkspace: false });
    expect(
      screen.getByText('A conta cheia do espaço — inclui o que outra pessoa vai pagar'),
    ).toBeInTheDocument();
  });

  it('não anuncia "nada a pagar" quando a consulta falhou', () => {
    // Um zero é uma informação financeira, e seria falsa (ERR-001).
    renderLista({ payables: undefined, isError: true });
    expect(screen.queryByText('Nenhuma conta em aberto')).not.toBeInTheDocument();
    expect(
      screen.getByText('Não foi possível carregar as suas contas a pagar.'),
    ).toBeInTheDocument();
  });
});

describe('Contas a pagar — confirmar o pagamento', () => {
  it('manda cada conta para o espaço DELA', async () => {
    renderLista();
    fireEvent.click(screen.getByLabelText(/Marcar Luz .* como paga/));
    fireEvent.click(screen.getByLabelText(/Marcar Pousada .* como paga/));
    fireEvent.click(screen.getByRole('button', { name: 'Marcar como paga' }));

    await waitFor(() => expect(mockSettle).toHaveBeenCalledTimes(2));
    const espacos = mockSettle.mock.calls.map(([args]) => args.workspaceId).sort();
    const ids = mockSettle.mock.calls.flatMap(([args]) => args.transactionIds).sort();
    // Duas chamadas, uma por casa. Uma só — com os dois ids — seria aceita pelo
    // servidor e não pagaria a conta da outra casa.
    expect(espacos).toEqual([1, 2]);
    expect(ids).toEqual([10, 20]);
  });

  it('envia a data em que o dinheiro saiu, não "agora"', async () => {
    renderLista();
    fireEvent.click(screen.getByLabelText(/Marcar Luz .* como paga/));
    fireEvent.change(screen.getByLabelText('Pago em'), {
      target: { value: '2026-08-14' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Marcar como paga' }));

    // É a data que decide em que mês a saída aparece no caixa: pagar no dia 14
    // uma conta confirmada no app hoje tem de mover o caixa do dia 14.
    await waitFor(() =>
      expect(mockSettle).toHaveBeenCalledWith(
        expect.objectContaining({ settledOn: '2026-08-14', settled: true }),
      ),
    );
  });

  it('a barra de confirmação só aparece com algo selecionado', () => {
    renderLista();
    expect(
      screen.queryByRole('button', { name: 'Marcar como paga' }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/Marcar Luz .* como paga/));
    expect(screen.getByText('1 conta selecionada')).toBeInTheDocument();
  });
});
