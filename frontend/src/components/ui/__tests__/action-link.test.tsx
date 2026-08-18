/**
 * Os gatilhos que não podem virar `<Button>` — e por isso ficavam de fora.
 *
 * "Marcar todas como lidas", "Marcar como lida", "Sair da conta" e o nome do
 * anexo eram `<button>` crus com estilo de link. Trocá-los por `Button` quebra
 * a linha (altura mínima, padding, gap de botão), então o que se compartilha é
 * o COMPORTAMENTO, via `useAcaoPendente`.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ActionLink } from '../action-link';
import { TransactionItem } from '@/components/money/TransactionItem';
import type { TransactionRead } from '@/types/transaction';

function promessaControlada() {
  let resolve!: () => void;
  const promessa = new Promise<void>((res) => {
    resolve = res;
  });
  return { promessa, resolve };
}

describe('ActionLink', () => {
  it('tranca no primeiro clique e destrava quando a ação assenta', async () => {
    const { promessa, resolve } = promessaControlada();
    const acao = vi.fn(() => promessa);
    render(<ActionLink onClick={acao}>Marcar como lida</ActionLink>);
    const link = screen.getByRole('button', { name: /marcar como lida/i });

    fireEvent.click(link);
    fireEvent.click(link);
    expect(acao).toHaveBeenCalledTimes(1);

    await waitFor(() => expect(link).toBeDisabled());
    expect(link).toHaveAttribute('aria-busy', 'true');

    resolve();
    await waitFor(() => expect(link).not.toBeDisabled());
  });

  it('gatilho síncrono continua clicável', () => {
    const acao = vi.fn();
    render(<ActionLink onClick={acao}>Abrir</ActionLink>);
    const link = screen.getByRole('button', { name: /abrir/i });

    fireEvent.click(link);
    fireEvent.click(link);
    expect(acao).toHaveBeenCalledTimes(2);
    expect(link).not.toBeDisabled();
  });
});

const TX: TransactionRead = {
  id: 1,
  title: 'Mercado',
  total_amount: '100.00',
  currency: 'BRL',
  status: 'paid',
  payment_method: 'pix',
  credit_card_id: null,
  transaction_date: '2026-08-18T12:00:00Z',
  splits: [],
} as unknown as TransactionRead;

describe('TransactionItem — excluir trava a LINHA, não a lista', () => {
  it('a linha que exclui se tranca e a vizinha segue clicável', async () => {
    const { promessa, resolve } = promessaControlada();
    const excluir = vi.fn(() => promessa);

    render(
      <>
        <TransactionItem tx={TX} canWrite onDelete={excluir} />
        <TransactionItem tx={{ ...TX, id: 2, title: 'Farmácia' }} canWrite onDelete={excluir} />
      </>,
    );

    const [primeiro, segundo] = screen.getAllByLabelText('Excluir transação');

    fireEvent.click(primeiro);
    fireEvent.click(primeiro);
    expect(excluir).toHaveBeenCalledTimes(1);

    await waitFor(() => expect(primeiro).toBeDisabled());
    // O estado é por linha: congelar a lista inteira faria uma exclusão lenta
    // parecer a tela travada.
    expect(segundo).not.toBeDisabled();

    fireEvent.click(segundo);
    expect(excluir).toHaveBeenCalledTimes(2);

    resolve();
    await waitFor(() => expect(primeiro).not.toBeDisabled());
  });
});
