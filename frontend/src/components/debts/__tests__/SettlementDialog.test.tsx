import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/setup';
import { describe, it, expect, beforeEach } from 'vitest';
import { SettlementDialog } from '../SettlementDialog';
import { useUIStore } from '@/stores';
import type { Member } from '@/hooks/use-members';

const WS = 'http://localhost:8000/api/v1/workspaces/1';

const members: Member[] = [
  { user_id: 1, role: 'owner', financial_access: 'full_workspace', user_name: 'Alice', user_email: 'a@t.com', joined_at: '2026-01-01' },
  { user_id: 2, role: 'member', financial_access: 'involved_only', user_name: 'Bob', user_email: 'b@t.com', joined_at: '2026-01-01' },
];

function renderDialog(
  onOpenChange: (open: boolean) => void = () => {},
  draft: React.ComponentProps<typeof SettlementDialog>['draft'] = {
    from_user_id: 2, to_user_id: 1, amount: 45,
  },
) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <SettlementDialog
        open
        onOpenChange={onOpenChange}
        draft={draft}
        members={members}
      />
    </QueryClientProvider>
  );
}

describe('SettlementDialog', () => {
  beforeEach(() => {
    useUIStore.getState().setCurrentWorkspaceId(1);
    server.use(http.get(`${WS}/settlements`, () => HttpResponse.json([])));
  });

  it('pré-preenche com a dívida e registra o acerto', async () => {
    let payload: Record<string, unknown> | null = null;
    server.use(
      http.post(`${WS}/settlements`, async ({ request }) => {
        payload = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: 1, ...payload, settled_at: '2026-07-18T12:00:00' });
      })
    );
    const closed: boolean[] = [];
    renderDialog((open) => closed.push(open));

    expect((screen.getByLabelText('Quem pagou') as HTMLSelectElement).value).toBe('2');
    expect((screen.getByLabelText('Quem recebeu') as HTMLSelectElement).value).toBe('1');

    fireEvent.change(screen.getByLabelText('Observação (opcional)'), { target: { value: 'Pix' } });
    fireEvent.click(screen.getByRole('button', { name: 'Registrar' }));

    await waitFor(() => expect(payload).not.toBeNull());
    expect(payload).toMatchObject({ from_user_id: 2, to_user_id: 1, amount: 45, note: 'Pix' });
    expect(closed).toContain(false);
  });

  it('exibe a mensagem de erro do envelope da API', async () => {
    server.use(
      http.post(`${WS}/settlements`, () =>
        HttpResponse.json(
          { error: { message: 'Usuário(s) [9] não pertence(m) a este workspace' } },
          { status: 400 }
        )
      )
    );
    renderDialog();

    fireEvent.click(screen.getByRole('button', { name: 'Registrar' }));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('não pertence');
  });

  /*
   * ADR 0027: na tela global há várias casas na mesma página e nenhuma na URL. A
   * casa do DRAFT tem de vencer a guardada na store, senão o acerto é registrado
   * na "última casa aberta" — que pode ser qualquer uma.
   */
  it('registra na casa do draft, não na que está na URL/store', async () => {
    useUIStore.getState().setCurrentWorkspaceId(1);
    let alvo: string | null = null;
    server.use(
      http.get('http://localhost:8000/api/v1/workspaces/2/settlements', () => HttpResponse.json([])),
      http.post('http://localhost:8000/api/v1/workspaces/2/settlements', async ({ request }) => {
        alvo = new URL(request.url).pathname;
        return HttpResponse.json({ id: 3, settled_at: '2026-08-13T12:00:00' });
      }),
    );

    renderDialog(() => {}, {
      from_user_id: 2, to_user_id: 1, amount: 45,
      workspace_id: 2, workspace_name: 'Viagem', currency: 'USD',
    });

    // O diálogo diz em qual casa o valor cai — é o que impede o registro errado.
    expect(screen.getByText(/abatido do balanço de Viagem/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Registrar' }));
    await waitFor(() => expect(alvo).toBe('/api/v1/workspaces/2/settlements'));
  });

  it('valida pagador == recebedor localmente', async () => {
    renderDialog();
    fireEvent.change(screen.getByLabelText('Quem recebeu'), { target: { value: '2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Registrar' }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('pessoas diferentes');
  });
});
