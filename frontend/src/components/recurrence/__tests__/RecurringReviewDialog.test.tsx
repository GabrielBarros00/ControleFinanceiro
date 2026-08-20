import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { RecurringReviewDialog } from '../RecurringReviewDialog';
import type { RecurringPlanItem } from '@/hooks/use-recurring';

/**
 * Revisão da edição de recorrência (ADR 0030).
 *
 * O que ela substitui: um `<select>` "Aplicar alterações a" no rodapé de um
 * modal longo, sem contagem, sem lista, e que não movia a data. A queixa de uso
 * foi exata — "alterar a recorrência não muda nada no Geral" —, e era verdade.
 *
 * Os dois erros que estes testes impedem:
 *
 * 1. **Mexer no que já foi pago.** A linha congelada tem de estar visível (a
 *    contagem precisa bater com o extrato) e ser impossível de marcar.
 * 2. **Aplicar o que não foi escolhido.** O que sai daqui é a lista de ids
 *    marcados; desmarcar uma linha tem de excluí-la da chamada.
 */
const PLANO: RecurringPlanItem[] = [
  {
    transaction_id: 10,
    occurrence_date: '2026-08-05',
    new_occurrence_date: '2026-08-20',
    billing_month: '2026-08',
    status: 'confirmed',
    action: 'move',
    frozen_reason: null,
    title: 'Aluguel',
    amount: '1000.00',
    changes: { date: { from: '2026-08-05', to: '2026-08-20' } },
  },
  {
    transaction_id: 11,
    occurrence_date: '2026-09-05',
    new_occurrence_date: null,
    billing_month: '2026-09',
    status: 'paid',
    action: 'none',
    frozen_reason: 'já paga — não será alterada',
    title: 'Aluguel',
    amount: '1000.00',
    changes: {},
  },
  {
    transaction_id: null,
    occurrence_date: '2026-10-20',
    new_occurrence_date: null,
    billing_month: '2026-10',
    status: null,
    action: 'create',
    frozen_reason: null,
    title: 'Aluguel',
    amount: '1000.00',
    changes: {},
  },
];

function renderDialog(props: Partial<Parameters<typeof RecurringReviewDialog>[0]> = {}) {
  const onConfirm = vi.fn().mockResolvedValue(undefined);
  const onSinceChange = vi.fn();
  render(
    <RecurringReviewDialog
      open
      onOpenChange={vi.fn()}
      action="update"
      items={PLANO}
      isLoading={false}
      since="2026-08-01"
      onSinceChange={onSinceChange}
      onConfirm={onConfirm}
      {...props}
    />,
  );
  return { onConfirm, onSinceChange };
}

describe('Revisão da recorrência — o que vai acontecer', () => {
  it('mostra a data de origem e a de destino de quem muda de dia', () => {
    // O defeito de origem: "todo dia 5" virava "todo dia 20" e os lançamentos
    // já criados ficavam no dia 5, sem nada na tela dizendo isso.
    renderDialog();
    expect(screen.getByText('05/08/2026 → 20/08/2026')).toBeInTheDocument();
    expect(screen.getByText('muda de data')).toBeInTheDocument();
  });

  it('lista a linha já paga, com o motivo, e não deixa marcá-la', () => {
    renderDialog();
    expect(screen.getByText('já paga — não será alterada')).toBeInTheDocument();
    // Visível E travada: escondê-la faria a contagem da tela não bater com o
    // extrato; deixá-la marcável prometeria o que o servidor vai recusar.
    expect(screen.getByLabelText(/05\/09\/2026/)).toBeDisabled();
  });

  it('resume o que foi selecionado', () => {
    renderDialog();
    expect(screen.getByText('1 muda(m) de data · 1 criado(s)')).toBeInTheDocument();
  });
});

describe('Revisão da recorrência — o que é aplicado', () => {
  it('manda só as linhas marcadas, separando ids de datas a criar', async () => {
    const { onConfirm } = renderDialog();
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar' }));

    await waitFor(() =>
      expect(onConfirm).toHaveBeenCalledWith({
        applyTo: [10],
        // A ocorrência que ainda não existe não tem id: ela viaja pela data.
        createOccurrences: ['2026-10-20'],
      }),
    );
  });

  it('desmarcar uma linha a tira da aplicação', async () => {
    const { onConfirm } = renderDialog();
    fireEvent.click(screen.getByLabelText(/05\/08\/2026/));
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar' }));

    await waitFor(() =>
      expect(onConfirm).toHaveBeenCalledWith({
        applyTo: [],
        createOccurrences: ['2026-10-20'],
      }),
    );
  });

  it('mudar "aplicar a partir de" refaz o plano', () => {
    // Sem isso o campo seria decoração: a lista continuaria mostrando meses que
    // o filtro diz ter excluído.
    const { onSinceChange } = renderDialog();
    fireEvent.change(screen.getByLabelText('Aplicar a partir de'), {
      target: { value: '2026-09' },
    });
    expect(onSinceChange).toHaveBeenCalledWith('2026-09-01');
  });

  it('excluir usa o vocabulário de exclusão, não o de edição', () => {
    renderDialog({ action: 'delete' });
    expect(
      screen.getByText('Excluir — e os lançamentos já criados?'),
    ).toBeInTheDocument();
  });
});
