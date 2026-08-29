import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { StatementMover } from '../StatementMover';
import { naJanelaDeFechamento } from '@/hooks/use-credit-cards';
import type { TransactionRead } from '@/types/transaction';

/**
 * Mover a compra de fatura DEPOIS de lançada (ADR 0032).
 *
 * É a metade que resolve o problema. No formulário, marcar que a compra vai
 * escorregar é palpite — ninguém sabe, ao passar o cartão, se o estabelecimento
 * vai demorar a capturar. Aqui a dúvida já virou fato: a fatura real chegou e não
 * bateu com a da tela.
 */
const OPCOES = [
  {
    shift: -1, month: '2026-06', closing_date: '2026-06-28T00:00:00',
    due_date: '2026-07-10T00:00:00', exists: true, available: false, status: 'closed',
  },
  {
    shift: 0, month: '2026-07', closing_date: '2026-07-28T00:00:00',
    due_date: '2026-08-10T00:00:00', exists: true, available: true, status: 'open',
  },
  {
    shift: 1, month: '2026-08', closing_date: '2026-08-28T00:00:00',
    due_date: '2026-09-10T00:00:00', exists: false, available: true, status: null,
  },
  {
    shift: 2, month: '2026-09', closing_date: '2026-09-28T00:00:00',
    due_date: '2026-10-10T00:00:00', exists: false, available: true, status: null,
  },
];

let alvo: unknown = {
  month: '2026-07', closing_date: '2026-07-28T00:00:00', due_date: '2026-08-10T00:00:00',
  exists: true, rolled_forward: false, shift: 0, days_to_closing: 1, options: OPCOES,
};

vi.mock('@/hooks/use-credit-cards', async (importOriginal) => ({
  // `importOriginal`: `naJanelaDeFechamento` é uma função PURA do mesmo módulo e
  // este arquivo a testa de verdade. Mocar o módulo inteiro a substituiria por
  // `undefined` e o teste dela passaria a medir o mock.
  ...(await importOriginal<typeof import('@/hooks/use-credit-cards')>()),
  useStatementTarget: () => ({ target: alvo, isLoading: false }),
}));

const COMPRA: TransactionRead = {
  id: 7,
  title: 'Restaurante',
  total_amount: '120.00',
  currency: 'BRL',
  transaction_date: '2026-07-27T15:00:00Z',
  billing_month: '2026-07',
  status: 'confirmed',
  credit_card_id: 3,
  statement_id: 55,
  statement_shift: 0,
  split_mode: 'transaction',
  payment_method: 'credit_card',
  created_at: '2026-07-27T15:00:00Z',
  updated_at: '2026-07-27T15:00:00Z',
  payers: [],
  splits: [],
  items: [],
} as unknown as TransactionRead;

const onMove = vi.fn().mockResolvedValue(undefined);

beforeEach(() => {
  onMove.mockClear();
  alvo = {
    month: '2026-07', closing_date: '2026-07-28T00:00:00', due_date: '2026-08-10T00:00:00',
    exists: true, rolled_forward: false, shift: 0, days_to_closing: 1, options: OPCOES,
  };
});

describe('a janela de fechamento', () => {
  it.each([
    [1, true],
    [3, true],
    [4, false],
    [0, false],
    [30, false],
  ])('%i dias para o fechamento → avisa? %s', (dias, esperado) => {
    expect(
      naJanelaDeFechamento({ days_to_closing: dias } as never)
    ).toBe(esperado);
  });

  it('não avisa quando o destino não é o ciclo natural da compra', () => {
    // `days_to_closing` vem `null` do servidor quando a compra já foi deslocada
    // ou a fatura rolou por estar fechada: nos dois casos o número compararia
    // ciclos diferentes, e avisar "faltam 2 dias" sobre uma compra que a própria
    // pessoa moveu seria contraditório.
    expect(naJanelaDeFechamento({ days_to_closing: null } as never)).toBe(false);
    expect(naJanelaDeFechamento(null)).toBe(false);
  });
});

describe('StatementMover', () => {
  it('lista as faturas alcançáveis com o mês e o vencimento', () => {
    render(<StatementMover transaction={COMPRA} canWrite onMove={onMove} />);
    const select = screen.getByLabelText('Fatura desta compra') as HTMLSelectElement;
    const rotulos = Array.from(select.options).map((o) => o.textContent);

    expect(rotulos[1]).toContain('Julho de 2026');
    expect(rotulos[1]).toContain('pela data da compra');
    expect(rotulos[2]).toContain('Agosto de 2026');
    expect(select.value).toBe('0');
  });

  it('mostra a fatura fechada DESABILITADA em vez de escondê-la', () => {
    // Escondê-la deixaria a tela sem explicação para a fatura que a pessoa
    // procura e não acha — e é o caso frequente, porque a divergência costuma
    // ser descoberta com o ciclo já fechado.
    render(<StatementMover transaction={COMPRA} canWrite onMove={onMove} />);
    const junho = Array.from(
      (screen.getByLabelText('Fatura desta compra') as HTMLSelectElement).options
    ).find((o) => o.value === '-1')!;

    expect(junho).toBeTruthy();
    expect(junho.disabled).toBe(true);
    expect(junho.textContent).toContain('fechada');
  });

  it('devolve o SHIFT da opção escolhida, não o mês', () => {
    // A aritmética de ciclo é do servidor (ADR 0002). A tela escolhe um mês e
    // devolve o número que veio junto dele — nunca um `statement_id`, que é o
    // que impedia apontar para a fatura de outro cartão.
    render(<StatementMover transaction={COMPRA} canWrite onMove={onMove} />);
    fireEvent.change(screen.getByLabelText('Fatura desta compra'), {
      target: { value: '1' },
    });
    expect(onMove).toHaveBeenCalledWith(1);
  });

  it('afirma que a competência NÃO se move', () => {
    // O medo legítimo de mexer aqui é "vou tirar o gasto do mês em que ele
    // aconteceu". É o invariante central do ADR 0032, dito onde a dúvida nasce.
    render(<StatementMover transaction={COMPRA} canWrite onMove={onMove} />);
    expect(screen.getByText(/muda a fatura, não o mês do gasto/i)).toBeInTheDocument();
    expect(screen.getByText('Julho de 2026')).toBeInTheDocument();
  });

  it('avisa que a compra parcelada desloca o cronograma inteiro', () => {
    render(
      <StatementMover
        transaction={{ ...COMPRA, installments_of: 12, installment_no: 1 }}
        canWrite
        onMove={onMove}
      />
    );
    expect(screen.getByText(/desloca o cronograma inteiro/i)).toBeInTheDocument();
  });

  it('não deixa mover sem permissão de escrita', () => {
    render(<StatementMover transaction={COMPRA} canWrite={false} onMove={onMove} />);
    expect(screen.getByLabelText('Fatura desta compra')).toBeDisabled();
  });

  it('não aparece em lançamento sem cartão', () => {
    const { container } = render(
      <StatementMover
        transaction={{ ...COMPRA, credit_card_id: null }}
        canWrite
        onMove={onMove}
      />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('mostra o erro quando a fatura de destino fechou no meio do caminho', async () => {
    onMove.mockRejectedValueOnce(new Error('409'));
    render(<StatementMover transaction={COMPRA} canWrite onMove={onMove} />);
    fireEvent.change(screen.getByLabelText('Fatura desta compra'), {
      target: { value: '1' },
    });
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/fatura de destino/i);
    });
  });
});
