import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/setup';
import { describe, it, expect, beforeEach } from 'vitest';
import { NewTransactionDialog } from '../NewTransactionDialog';
import { useAuthStore, useUIStore } from '@/stores';
import { ConfirmProvider } from '@/components/ui/confirm';

const WS = 'http://localhost:8000/api/v1/workspaces/1';

const members = [
  { user_id: 1, role: 'owner', user_name: 'Alice', user_email: 'alice@t.com', joined_at: '2026-01-01' },
  { user_id: 2, role: 'member', user_name: 'Bob', user_email: 'bob@t.com', joined_at: '2026-01-01' },
];

function renderForm() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const resultado = render(
    <QueryClientProvider client={queryClient}>
    {/* `ConfirmProvider`: o diálogo passou a PERGUNTAR antes de descartar um
        formulário preenchido (Escape ou clique fora jogavam fora título, valor,
        pagadores, divisão e anexos sem aviso). `useConfirm` lança sem o
        provider, exatamente como já acontecia no teste da Administração. */}
      <ConfirmProvider>
        <NewTransactionDialog open onOpenChange={() => {}} />
      </ConfirmProvider>
    </QueryClientProvider>
  );
  /*
   * O diálogo de CRIAÇÃO abre no modo simples — título, valor e salvar. Tudo o
   * que este arquivo exercita (pagadores, itens, divisão, anexos) mora atrás de
   * "Detalhar", que é o ponto da mudança: o formulário deixou de abrir com doze
   * controles para preencher dois campos.
   *
   * O clique fica no helper, e não em cada teste, porque ele não é o assunto de
   * nenhum deles: é a porta de entrada do formulário completo.
   */
  fireEvent.click(screen.getByRole('button', { name: /^Detalhar$/i }));
  return resultado;
}

async function fillBaseFields(total = '90,00') {
  fireEvent.change(screen.getByLabelText('Título / Descrição'), { target: { value: 'Mercado' } });
  fireEvent.change(screen.getByLabelText('Valor Total'), { target: { value: total } });
}

// A divisão %/fixo e a divisão por item moram em "Opções avançadas"
function openAdvanced() {
  fireEvent.click(screen.getByRole('button', { name: /Opções avançadas/i }));
}

async function addBobAsSecondParticipant() {
  fireEvent.click(screen.getByRole('button', { name: '+ Participante' }));
  const participantSelects = screen.getAllByLabelText('Participante');
  fireEvent.change(participantSelects[1], { target: { value: '2' } });
}

describe('NewTransactionDialog — método de divisão', () => {
  beforeEach(() => {
    useAuthStore.getState().setUser({ id: 1, name: 'Alice', email: 'alice@t.com' });
    useUIStore.getState().setCurrentWorkspaceId(1);
    server.use(
      http.get(`${WS}/members`, () => HttpResponse.json(members)),
      http.get(`${WS}/invites`, () => HttpResponse.json([])),
      http.get(`${WS}/categories`, () => HttpResponse.json([])),
      http.get(`${WS}/credit-cards/`, () => HttpResponse.json([])),
      http.get(`${WS}/tags`, () => HttpResponse.json([])),
    );
  });

  it('abre os inputs de percentual ao selecionar Porcentagem (regressão do bug do RadioGroup)', async () => {
    renderForm();
    await screen.findAllByText('Alice');
    openAdvanced();

    // Com "Igual" (default) não há input de valor por participante
    expect(screen.queryAllByLabelText('Percentual')).toHaveLength(0);

    fireEvent.click(screen.getByRole('radio', { name: 'Porcentagem' }));

    await waitFor(() => {
      expect(screen.getAllByLabelText('Percentual')).toHaveLength(1);
    });
  });

  it('abre os inputs de valor ao selecionar Valor Fixo', async () => {
    renderForm();
    await screen.findAllByText('Alice');
    openAdvanced();

    fireEvent.click(screen.getByRole('radio', { name: 'Valor Fixo' }));

    await waitFor(() => {
      expect(screen.getAllByLabelText('Valor fixo')).toHaveLength(1);
    });
  });

  it('bloqueia submit quando percentuais não somam 100 e mostra o que falta', async () => {
    let createCalled = false;
    server.use(
      http.post(`${WS}/transactions/`, () => {
        createCalled = true;
        return HttpResponse.json({ id: 1 });
      })
    );
    renderForm();
    await screen.findAllByText('Alice');

    await fillBaseFields();
    openAdvanced();
    fireEvent.click(screen.getByRole('radio', { name: 'Porcentagem' }));
    await addBobAsSecondParticipant();

    const percentInputs = screen.getAllByLabelText('Percentual');
    fireEvent.change(percentInputs[0], { target: { value: '60' } });
    fireEvent.change(percentInputs[1], { target: { value: '30' } });

    fireEvent.click(screen.getByRole('button', { name: 'Salvar despesa' }));

    await screen.findAllByText(/faltam 10%/);
    expect(createCalled).toBe(false);
  });

  it('envia split_method percentage com input_value correto quando soma 100', async () => {
    let payload: Record<string, unknown> | null = null;
    server.use(
      http.post(`${WS}/transactions/`, async ({ request }) => {
        payload = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: 1, ...payload });
      })
    );
    renderForm();
    await screen.findAllByText('Alice');

    await fillBaseFields();
    openAdvanced();
    fireEvent.click(screen.getByRole('radio', { name: 'Porcentagem' }));
    await addBobAsSecondParticipant();

    const percentInputs = screen.getAllByLabelText('Percentual');
    fireEvent.change(percentInputs[0], { target: { value: '60' } });
    fireEvent.change(percentInputs[1], { target: { value: '40' } });

    fireEvent.click(screen.getByRole('button', { name: 'Salvar despesa' }));

    await waitFor(() => expect(payload).not.toBeNull());
    expect(payload!.total_amount).toBe(90);
    expect(payload!.splits).toEqual([
      { user_id: 1, split_method: 'percentage', input_value: 60 },
      { user_id: 2, split_method: 'percentage', input_value: 40 },
    ]);
  });

  it('bloqueia submit quando valores fixos não fecham o total', async () => {
    let createCalled = false;
    server.use(
      http.post(`${WS}/transactions/`, () => {
        createCalled = true;
        return HttpResponse.json({ id: 1 });
      })
    );
    renderForm();
    await screen.findAllByText('Alice');

    await fillBaseFields('90,00');
    openAdvanced();
    fireEvent.click(screen.getByRole('radio', { name: 'Valor Fixo' }));
    await addBobAsSecondParticipant();

    const fixedInputs = screen.getAllByLabelText('Valor fixo');
    fireEvent.change(fixedInputs[0], { target: { value: '50,00' } });
    fireEvent.change(fixedInputs[1], { target: { value: '30,00' } });

    fireEvent.click(screen.getByRole('button', { name: 'Salvar despesa' }));

    await screen.findAllByText(/faltam R\$\s*10,00/);
    expect(createCalled).toBe(false);
  });

  it('envia split_method fixed quando os valores fecham o total', async () => {
    let payload: Record<string, unknown> | null = null;
    server.use(
      http.post(`${WS}/transactions/`, async ({ request }) => {
        payload = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: 1, ...payload });
      })
    );
    renderForm();
    await screen.findAllByText('Alice');

    await fillBaseFields('90,00');
    openAdvanced();
    fireEvent.click(screen.getByRole('radio', { name: 'Valor Fixo' }));
    await addBobAsSecondParticipant();

    const fixedInputs = screen.getAllByLabelText('Valor fixo');
    fireEvent.change(fixedInputs[0], { target: { value: '50,00' } });
    fireEvent.change(fixedInputs[1], { target: { value: '40,00' } });

    fireEvent.click(screen.getByRole('button', { name: 'Salvar despesa' }));

    await waitFor(() => expect(payload).not.toBeNull());
    expect(payload!.splits).toEqual([
      { user_id: 1, split_method: 'fixed', input_value: 50 },
      { user_id: 2, split_method: 'fixed', input_value: 40 },
    ]);
  });

  it('bloqueia participante repetido na divisão', async () => {
    let createCalled = false;
    server.use(
      http.post(`${WS}/transactions/`, () => {
        createCalled = true;
        return HttpResponse.json({ id: 1 });
      })
    );
    renderForm();
    await screen.findAllByText('Alice');

    await fillBaseFields();
    openAdvanced();
    fireEvent.click(screen.getByRole('button', { name: '+ Participante' }));
    const participantSelects = screen.getAllByLabelText('Participante');
    fireEvent.change(participantSelects[1], { target: { value: '1' } });

    fireEvent.click(screen.getByRole('button', { name: 'Salvar despesa' }));

    await screen.findByText('Participante repetido na divisão');
    expect(createCalled).toBe(false);
  });

  it('exibe a mensagem de erro do envelope da API em vez de alert genérico', async () => {
    server.use(
      http.post(`${WS}/transactions/`, () =>
        HttpResponse.json(
          { error: { message: 'Divisão inválida: percentuais devem somar 100' } },
          { status: 400 }
        )
      )
    );
    renderForm();
    await screen.findAllByText('Alice');

    await fillBaseFields();
    fireEvent.click(screen.getByRole('button', { name: 'Salvar despesa' }));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Divisão inválida: percentuais devem somar 100');
  });
});
