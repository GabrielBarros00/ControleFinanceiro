import { describe, expect, it, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { fireEvent, render, screen, waitFor, within } from '@/test/utils';
import { server } from '@/test/setup';
import { IncomePage } from '../IncomePage';

/**
 * Categoria, conta e observação da renda — e, na recorrente, "confirmar sozinha".
 *
 * O agente de IA grava os quatro ("salário, cai no Itaú"; "freela: não confirme
 * sozinho"), e a tela não mostrava nem editava nenhum. A renda aparecia sem
 * detalhe, e quem quisesse corrigir a conta tinha de pedir à IA.
 */

vi.mock('@/components/ui/confirm', () => ({ useConfirm: () => vi.fn() }));

const API = 'http://localhost:8000/api/v1';

const SALARIO = {
  id: 1, user_id: 1, title: 'Salário', amount: '5000.00', currency: 'BRL', status: 'expected',
  received_at: '2026-09-05T15:00:00', created_at: '2026-09-01T00:00:00', updated_at: '2026-09-01T00:00:00',
  category: 'Salário', account_id: 3, description: 'Com 13º adiantado',
};

const FREELA = {
  id: 7, user_id: 1, title: 'Freela', base_amount: '800.00', currency: 'BRL', category: 'Freela',
  description: 'Cliente X', frequency: 'monthly', interval: 1, day_of_month: 10, is_active: true,
  auto_confirm: false, account_id: 3,
};

function backend(onPut: (url: string, corpo: Record<string, unknown>) => void) {
  server.use(
    http.get(`${API}/me/overview`, () => HttpResponse.json({ currency: 'BRL' })),
    http.get(`${API}/me/payment-accounts`, () => HttpResponse.json([
      { id: 3, name: 'Itaú', currency: 'BRL', active: true, kind: 'checking' },
      { id: 4, name: 'Nubank', currency: 'BRL', active: true, kind: 'checking' },
    ])),
    http.get(`${API}/me/income/`, () => HttpResponse.json([SALARIO])),
    http.get(`${API}/me/recurring-income`, () => HttpResponse.json([FREELA])),
    http.put(`${API}/me/income/:id`, async ({ request }) => {
      const corpo = (await request.json()) as Record<string, unknown>;
      onPut(request.url, corpo);
      return HttpResponse.json({ ...SALARIO, ...corpo });
    }),
    http.put(`${API}/me/recurring-income/:id`, async ({ request }) => {
      const corpo = (await request.json()) as Record<string, unknown>;
      onPut(request.url, corpo);
      return HttpResponse.json({ ...FREELA, ...corpo });
    }),
  );
}

describe('Rendas — categoria, conta e observação', () => {
  it('a lista mostra a categoria, a conta e a observação', async () => {
    backend(() => {});
    render(<IncomePage />);
    expect((await screen.findAllByText('Salário · cai em Itaú · Com 13º adiantado')).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Freela · cai em Itaú · Cliente X').length).toBeGreaterThan(0);
  });

  it('editar a renda abre os três e devolve o que está na tela', async () => {
    let corpo: Record<string, unknown> | null = null;
    backend((_, c) => { corpo = c; });
    render(<IncomePage />);
    fireEvent.click((await screen.findAllByRole('button', { name: 'Editar renda Salário' }))[0]);

    const dialogo = screen.getByRole('dialog');
    expect((within(dialogo).getByLabelText('Categoria (opcional)') as HTMLInputElement).value).toBe('Salário');
    expect((within(dialogo).getByLabelText('Observação (opcional)') as HTMLInputElement).value).toBe('Com 13º adiantado');
    await waitFor(() =>
      expect((within(dialogo).getByLabelText('Conta onde cai') as HTMLSelectElement).value).toBe('3'));

    fireEvent.change(within(dialogo).getByLabelText('Conta onde cai'), { target: { value: '4' } });
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Salvar' }));

    await waitFor(() => expect(corpo).not.toBeNull());
    expect(corpo).toMatchObject({ category: 'Salário', description: 'Com 13º adiantado', account_id: 4 });
  });

  it('a recorrente abre "confirmar sozinha" como está, e o devolve', async () => {
    let corpo: Record<string, unknown> | null = null;
    backend((_, c) => { corpo = c; });
    render(<IncomePage />);
    fireEvent.click((await screen.findAllByRole('button', { name: 'Editar renda recorrente Freela' }))[0]);

    const dialogo = screen.getByRole('dialog');
    expect(within(dialogo).getByRole('switch', { name: 'Confirmar sozinha na data' })).not.toBeChecked();
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Salvar' }));

    await waitFor(() => expect(corpo).not.toBeNull());
    expect(corpo).toMatchObject({ auto_confirm: false, account_id: 3, category: 'Freela', description: 'Cliente X' });
  });
});
