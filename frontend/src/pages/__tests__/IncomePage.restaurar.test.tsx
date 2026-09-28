import { describe, expect, it, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { fireEvent, render, screen, waitFor } from '@/test/utils';
import { server } from '@/test/setup';
import { IncomePage } from '../IncomePage';

vi.mock('@/components/ui/confirm', () => ({ useConfirm: () => vi.fn() }));

const API = 'http://localhost:8000/api/v1';
const renda = {
  id: 8, user_id: 1, title: 'Freela excluído', amount: '500.00', currency: 'BRL',
  status: 'expected', received_at: '2026-09-15T15:00:00',
  created_at: '2026-09-01T00:00:00', updated_at: '2026-09-01T00:00:00',
};

describe('Rendas excluídas', () => {
  it('permite encontrar uma renda antiga e restaurá-la após o aviso de exclusão sumir', async () => {
    let restaurada = false;
    server.use(
      http.get(`${API}/me/overview`, () => HttpResponse.json({ currency: 'BRL' })),
      http.get(`${API}/me/recurring-income`, () => HttpResponse.json([])),
      http.get(`${API}/me/income/`, ({ request }) => {
        const deleted = new URL(request.url).searchParams.get('deleted') === 'true';
        return HttpResponse.json(deleted ? (restaurada ? [] : [renda]) : (restaurada ? [renda] : []));
      }),
      http.post(`${API}/me/income/8/restore`, () => {
        restaurada = true;
        return HttpResponse.json(renda);
      }),
    );
    render(<IncomePage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Ver excluídas' }));
    expect(await screen.findByText('Freela excluído')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Restaurar' }));
    await waitFor(() => expect(restaurada).toBe(true));
    await waitFor(() => expect(screen.getByText('Nenhuma renda excluída')).toBeInTheDocument());
  });
});
