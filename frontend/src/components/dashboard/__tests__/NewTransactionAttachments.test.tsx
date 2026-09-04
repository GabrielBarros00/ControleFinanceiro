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
];

function renderForm() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
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
}

function pick(...files: File[]) {
  fireEvent.change(screen.getByLabelText('Enviar anexo'), { target: { files } });
}

function fillBaseFields() {
  fireEvent.change(screen.getByLabelText('Título / Descrição'), { target: { value: 'Mercado' } });
  fireEvent.change(screen.getByLabelText('Valor Total'), { target: { value: '90,00' } });
}

// Anexar só era possível editando uma despesa já salva; na criação os arquivos
// ficam em espera e sobem assim que o POST devolve o id.
describe('NewTransactionDialog — anexos na criação', () => {
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

  it('sobe na despesa recém-criada os arquivos escolhidos antes de salvar', async () => {
    // O multipart em si não sobrevive ao jsdom (axios cai no adapter de Node);
    // o que este teste garante é o encadeamento: id devolvido pelo POST da
    // despesa → um upload por arquivo em espera.
    const uploaded: string[] = [];
    server.use(
      http.post(`${WS}/transactions/`, () => HttpResponse.json({ id: 77 })),
      http.post(`${WS}/transactions/:txId/attachments`, ({ params }) => {
        uploaded.push(String(params.txId));
        return HttpResponse.json({
          id: uploaded.length,
          transaction_id: 77,
          filename: 'anexo',
          content_type: 'application/pdf',
          size_bytes: 10,
          created_at: '2026-07-28T00:00:00Z',
        });
      }),
    );
    renderForm();
    await screen.findAllByText('Alice');
    fillBaseFields();

    pick(
      new File(['%PDF-1.7 nota'], 'nota.pdf', { type: 'application/pdf' }),
      new File(['\x89PNG recibo'], 'recibo.png', { type: 'image/png' }),
    );
    await screen.findByText('nota.pdf');
    expect(screen.getByText('recibo.png')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Salvar despesa' }));

    await waitFor(() => expect(uploaded).toEqual(['77', '77']));
  });

  it('recusa tipo não suportado sem esperar o backend', async () => {
    renderForm();
    await screen.findAllByText('Alice');

    pick(new File(['MZ'], 'virus.exe', { type: 'application/x-msdownload' }));

    await screen.findByText(/use JPG, PNG, WebP ou PDF/);
    expect(screen.queryByText('virus.exe')).toBeNull();
  });

  it('remove um arquivo da lista antes de salvar', async () => {
    let payloadSent = false;
    server.use(
      http.post(`${WS}/transactions/`, () => {
        payloadSent = true;
        return HttpResponse.json({ id: 5 });
      }),
    );
    renderForm();
    await screen.findAllByText('Alice');
    fillBaseFields();

    pick(new File(['%PDF-1.7'], 'errado.pdf', { type: 'application/pdf' }));
    await screen.findByText('errado.pdf');

    fireEvent.click(screen.getByRole('button', { name: 'Remover anexo errado.pdf' }));
    await waitFor(() => expect(screen.queryByText('errado.pdf')).toBeNull());

    // Sem anexo pendente, salvar não dispara nenhum upload (nenhuma rota de
    // anexo está registrada — um POST extra derrubaria o teste)
    fireEvent.click(screen.getByRole('button', { name: 'Salvar despesa' }));
    await waitFor(() => expect(payloadSent).toBe(true));
  });
});
