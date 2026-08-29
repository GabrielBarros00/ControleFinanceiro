import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { FormProvider, useForm } from 'react-hook-form';
import { PaymentMethodField } from '../PaymentMethodField';
import type { TransactionFormValues } from '../schema';

/**
 * O aviso da janela de fechamento (ADR 0032).
 *
 * A fatura real é composta pela data em que o EMISSOR processa a compra. Perto
 * do fechamento, o atraso de captura do estabelecimento decide em qual fatura
 * ela cai — e este é o único momento em que o app pode avisar ANTES do fato.
 *
 * O aviso vale mais do que o atalho que vem com ele: no formulário, marcar que a
 * compra vai escorregar é palpite. O conserto de verdade é poder mover depois
 * (`StatementMover`), quando a fatura real chegou.
 */
const OPCOES = [
  { shift: -1, month: '2026-06', closing_date: '2026-06-28T00:00:00', due_date: '2026-07-10T00:00:00', exists: true, available: true, status: 'open' },
  { shift: 0, month: '2026-07', closing_date: '2026-07-28T00:00:00', due_date: '2026-08-10T00:00:00', exists: true, available: true, status: 'open' },
  { shift: 1, month: '2026-08', closing_date: '2026-08-28T00:00:00', due_date: '2026-09-10T00:00:00', exists: false, available: true, status: null },
  { shift: 2, month: '2026-09', closing_date: '2026-09-28T00:00:00', due_date: '2026-10-10T00:00:00', exists: false, available: true, status: null },
];

const alvoBase = {
  month: '2026-07',
  closing_date: '2026-07-28T00:00:00',
  due_date: '2026-08-10T00:00:00',
  exists: true,
  rolled_forward: false,
  shift: 0,
  days_to_closing: 1,
  options: OPCOES,
};

let alvo: typeof alvoBase = alvoBase;

vi.mock('@/hooks/use-credit-cards', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/hooks/use-credit-cards')>()),
  useCreditCards: () => ({ cards: [{ id: 3, name: 'Nubank' }] }),
  useStatementTarget: () => ({ target: alvo, isLoading: false }),
}));

vi.mock('@/hooks/use-payment-accounts', () => ({
  usePaymentAccounts: () => ({ activeAccounts: [] }),
}));

function Formulario({ shift = 0 }: { shift?: number }) {
  const methods = useForm<TransactionFormValues>({
    defaultValues: {
      title: 'Restaurante',
      total_amount: 120,
      currency: 'BRL',
      transaction_date: '2026-07-27',
      payers: [{ user_id: '1', amount: 120, payment_method: '', account_id: '' }],
      payment_method: 'credit_card',
      credit_card_id: '3',
      statement_shift: shift,
      installments: 1,
      category_id: '',
      tag_ids: [],
      split_mode: 'transaction',
      split_method: 'equal',
      splits: [],
      items: [],
      settled: true,
    } as TransactionFormValues,
  });
  return (
    <FormProvider {...methods}>
      <PaymentMethodField />
    </FormProvider>
  );
}

beforeEach(() => {
  alvo = alvoBase;
});

describe('aviso da janela de fechamento', () => {
  it('avisa na véspera do fechamento', () => {
    render(<Formulario />);
    const aviso = screen.getByTestId('closing-window-warning');
    expect(aviso).toHaveTextContent('Falta 1 dia para o fechamento');
    expect(aviso).toHaveTextContent(/pode jogar esta compra para a fatura seguinte/i);
    // A promessa que torna o palpite desnecessário: dá para consertar depois.
    expect(aviso).toHaveTextContent(/ajustar depois/i);
  });

  it('concorda com o plural', () => {
    alvo = { ...alvoBase, days_to_closing: 3 };
    render(<Formulario />);
    expect(screen.getByTestId('closing-window-warning')).toHaveTextContent(
      'Faltam 3 dias para o fechamento'
    );
  });

  it('NÃO avisa fora da janela de três dias', () => {
    // Cinco dias fariam o aviso aparecer em uma de cada seis compras no cartão,
    // e um aviso quase sempre falso fica invisível em duas semanas — aí falha
    // justamente na compra em que importava.
    alvo = { ...alvoBase, days_to_closing: 4 };
    render(<Formulario />);
    expect(screen.queryByTestId('closing-window-warning')).not.toBeInTheDocument();
  });

  it('NÃO avisa quando a compra já abriu o ciclo seguinte', () => {
    // Depois do fechamento o atraso de captura não muda nada: 1 a 3 dias nunca
    // atravessam um ciclo inteiro. O aviso é unilateral por natureza.
    alvo = { ...alvoBase, month: '2026-08', days_to_closing: 30 };
    render(<Formulario />);
    expect(screen.queryByTestId('closing-window-warning')).not.toBeInTheDocument();
  });

  it('NÃO avisa quando o destino já foi deslocado', () => {
    // `days_to_closing` vem `null` do servidor: avisar "faltam 2 dias para o
    // fechamento" sobre uma compra que a própria pessoa moveu seria contraditório.
    alvo = { ...alvoBase, days_to_closing: null as unknown as number, shift: 1 };
    render(<Formulario shift={1} />);
    expect(screen.queryByTestId('closing-window-warning')).not.toBeInTheDocument();
  });

  it('continua anunciando o destino da fatura fora da janela', () => {
    // O hint sempre existiu e não pode desaparecer junto com o aviso novo.
    alvo = { ...alvoBase, days_to_closing: 20 };
    render(<Formulario />);
    expect(screen.getByTestId('statement-target-hint')).toHaveTextContent(
      /Vai para a fatura de Julho de 2026/
    );
  });
});

describe('o atalho "esta loja costuma demorar"', () => {
  it('oferece a fatura seguinte na janela, dizendo que a competência não muda', () => {
    render(<Formulario />);
    const caixa = screen.getByRole('checkbox', { name: /costuma demorar/i });
    expect(caixa).not.toBeChecked();
    expect(screen.getByText(/muda a fatura, não o mês do gasto/i)).toBeInTheDocument();
    // O mês da competência sai da DATA da compra, não do destino da fatura.
    expect(screen.getByText(/A despesa continua sendo de Julho de 2026/)).toBeInTheDocument();
  });

  it('marca o deslocamento no formulário', () => {
    render(<Formulario />);
    fireEvent.click(screen.getByRole('checkbox', { name: /costuma demorar/i }));
    expect(screen.getByRole('checkbox', { name: /costuma demorar/i })).toBeChecked();
  });

  it('não aparece fora da janela', () => {
    alvo = { ...alvoBase, days_to_closing: 15 };
    render(<Formulario />);
    expect(screen.queryByRole('checkbox', { name: /costuma demorar/i })).not.toBeInTheDocument();
  });

  it('continua visível quando JÁ marcado, mesmo fora da janela', () => {
    // Senão desmarcar faria a caixa sumir antes de o efeito ser visível, e não
    // haveria como voltar atrás sem recarregar o formulário.
    alvo = { ...alvoBase, days_to_closing: null as unknown as number, shift: 1 };
    render(<Formulario shift={1} />);
    expect(screen.getByRole('checkbox', { name: /costuma demorar/i })).toBeChecked();
  });
});
