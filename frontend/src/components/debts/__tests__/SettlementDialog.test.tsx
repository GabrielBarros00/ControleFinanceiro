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

function renderDialog(onOpenChange: (open: boolean) => void = () => {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <SettlementDialog
        open
        onOpenChange={onOpenChange}
        draft={{ from_user_id: 2, to_user_id: 1, amount: 45 }}
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

  it('valida pagador == recebedor localmente', async () => {
    renderDialog();
    fireEvent.change(screen.getByLabelText('Quem recebeu'), { target: { value: '2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Registrar' }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('pessoas diferentes');
  });
});
