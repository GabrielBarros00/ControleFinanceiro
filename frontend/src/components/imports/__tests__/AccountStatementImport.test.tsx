import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/setup';
import { useUIStore } from '@/stores';
import { AccountStatementImport } from '../AccountStatementImport';

/**
 * Importar o extrato de uma conta (ADR 0037). O que não pode errar: o sinal
 * (entrou/saiu) aparece e limita o que a linha pode ser; o palpite do servidor
 * vem marcado; o que já foi importado começa ignorado; e a gravação manda, para
 * cada linha, só o destino que a classificação usa.
 */
const API = 'http://localhost:8000/api/v1';

const linha = (extra: Record<string, unknown>) => ({
  line: 2, title: 'X', total_amount: '10.00', transaction_date: '2026-09-20T15:00:00', direction: 'out',
  external_id: null, duplicate: false, suggested_classification: 'expense', suggested_card_id: null, suggested_account_id: null,
  ...extra,
});

function servidor(commit = vi.fn()) {
  server.use(
    http.get(`${API}/me/payment-accounts`, () => HttpResponse.json([
      { id: 3, name: 'Itaú', type: 'checking', currency: 'BRL', active: true },
      { id: 4, name: 'Poupança', type: 'savings', currency: 'BRL', active: true },
    ])),
    http.get(`${API}/me/credit-cards/`, () => HttpResponse.json([{ id: 7, name: 'Nubank Roxinho' }])),
    http.get(`${API}/workspaces/`, () => HttpResponse.json([{ id: 1, name: 'Casa' }, { id: 2, name: 'Viagem' }])),
    http.post(`${API}/me/imports/parse`, () => HttpResponse.json({
      account_id: 3, currency: 'BRL', skipped: [],
      rows: [
        linha({ line: 2, title: 'SALARIO', total_amount: '5000.00', direction: 'in', suggested_classification: 'income' }),
        linha({ line: 3, title: 'MERCADO', total_amount: '89.90' }),
        linha({ line: 4, title: 'PAGAMENTO FATURA', total_amount: '300.00', suggested_classification: 'statement_payment', suggested_card_id: 7 }),
        linha({ line: 5, title: 'TRANSF POUPANCA', total_amount: '1000.00', suggested_classification: 'transfer', suggested_account_id: 4 }),
        linha({ line: 6, title: 'JA VEIO', total_amount: '5.00', duplicate: true }),
      ],
    })),
    http.post(`${API}/me/imports/commit`, async ({ request }) => {
      commit(await request.json());
      return HttpResponse.json({
        batch_id: 9, imported: 3, ignored: 1, duplicate: 0, skipped: 1,
        by_classification: { income: 1, expense: 1, transfer: 1 }, problems: [{ line: 4, reason: 'o Nubank não tem fatura com saldo' }],
      });
    }),
  );
  return commit;
}

async function processa() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <AccountStatementImport />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const conta = screen.getByLabelText('Conta do extrato');
  await waitFor(() => expect(within(conta).getByRole('option', { name: 'Itaú' })).toBeInTheDocument());
  fireEvent.change(conta, { target: { value: '3' } });
  fireEvent.change(screen.getByLabelText('Arquivo CSV'), { target: { files: [new File(['x'], 'itau.csv', { type: 'text/csv' })] } });
  fireEvent.click(screen.getByRole('button', { name: /Processar extrato/ }));
  await screen.findByText('SALARIO');
}

describe('AccountStatementImport', () => {
  beforeEach(() => {
    useUIStore.getState().setCurrentWorkspaceId(1);
  });

  it('mostra o sinal, o palpite, e só as classificações que o sentido permite', async () => {
    servidor();
    await processa();
    expect(screen.getByText(/\+R\$\s?5\.000,00/)).toBeInTheDocument();
    expect(screen.getByText(/−R\$\s?89,90/)).toBeInTheDocument();
    const salario = screen.getByLabelText('O que é "SALARIO"') as HTMLSelectElement;
    expect(salario.value).toBe('income');
    expect([...salario.options].map((o) => o.textContent)).toEqual(['Renda', 'Transferência', 'Ignorar']);
    expect((screen.getByLabelText('O que é "PAGAMENTO FATURA"') as HTMLSelectElement).value).toBe('statement_payment');
    expect((screen.getByLabelText('Cartão de "PAGAMENTO FATURA"') as HTMLSelectElement).value).toBe('7');
    expect((screen.getByLabelText('Outra conta de "TRANSF POUPANCA"') as HTMLSelectElement).value).toBe('4');
    // A conta do próprio extrato não é destino de transferência.
    expect(within(screen.getByLabelText('Outra conta de "TRANSF POUPANCA"')).queryByRole('option', { name: 'Itaú' })).not.toBeInTheDocument();
    // Já importada começa ignorada.
    expect((screen.getByLabelText('O que é "JA VEIO"') as HTMLSelectElement).value).toBe('ignore');
    expect(screen.getByRole('button', { name: 'Importar 4' })).toBeInTheDocument();
  });

  it('grava cada linha com o destino da sua classificação e mostra o que não entrou', async () => {
    const commit = servidor();
    await processa();
    fireEvent.click(screen.getByRole('button', { name: 'Importar 4' }));
    await waitFor(() => expect(commit).toHaveBeenCalled());
    const corpo = commit.mock.calls[0][0];
    expect(corpo.account_id).toBe(3);
    const porLinha = Object.fromEntries(corpo.rows.map((r: Record<string, unknown>) => [r.line, r]));
    expect(porLinha[2]).toMatchObject({ direction: 'in', decision: 'import', classification: 'income', space_id: null, card_id: null });
    // Sem espaço escolhido na linha, a despesa vai para o espaço aberto.
    expect(porLinha[3]).toMatchObject({ classification: 'expense', space_id: 1, counterpart_account_id: null });
    expect(porLinha[4]).toMatchObject({ classification: 'statement_payment', card_id: 7, space_id: null });
    expect(porLinha[5]).toMatchObject({ classification: 'transfer', counterpart_account_id: 4 });
    expect(porLinha[6]).toMatchObject({ decision: 'ignore', classification: null });
    expect(await screen.findByText('Linha 4: o Nubank não tem fatura com saldo')).toBeInTheDocument();
  });
});
