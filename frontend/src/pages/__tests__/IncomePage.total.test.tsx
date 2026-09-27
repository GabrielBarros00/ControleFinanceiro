import { describe, expect, it, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { render, screen } from '@/test/utils';
import { server } from '@/test/setup';
import { IncomePage } from '../IncomePage';

/**
 * O total do subtítulo de Rendas é a renda DO MÊS, com a mesma regra do backend
 * (`OverviewService._renda_de_competencia`): recebida ou prevista entram, a
 * CANCELADA não — a pessoa já disse que ela não vem.
 *
 * A tela somava a lista inteira: com uma renda cancelada de R$ 500 no mês, o
 * subtítulo dizia R$ 15.441,60 e a Visão global R$ 14.941,60 (auditoria de
 * 2026-09-26, C5).
 */

vi.mock('@/components/ui/confirm', () => ({ useConfirm: () => vi.fn() }));

const API = 'http://localhost:8000/api/v1';

function renda(id: number, amount: string, status: string, extra: Record<string, unknown> = {}) {
  return {
    id, user_id: 1, title: `Renda ${id}`, amount, currency: 'BRL', status,
    received_at: '2026-09-05T15:00:00', created_at: '2026-09-01T00:00:00',
    updated_at: '2026-09-01T00:00:00', ...extra,
  };
}

describe('Rendas — total do mês', () => {
  it('soma recebidas e previstas, e deixa a cancelada de fora', async () => {
    server.use(
      http.get(`${API}/me/overview`, () => HttpResponse.json({ currency: 'BRL' })),
      http.get(`${API}/me/recurring-income`, () => HttpResponse.json([])),
      http.get(`${API}/me/income/`, () => HttpResponse.json([
        renda(1, '9800.00', 'received', { settled_at: '2026-09-05T15:00:00' }),
        renda(2, '5141.60', 'expected'),
        renda(3, '500.00', 'cancelled', { cancelled_at: '2026-09-20T15:00:00' }),
      ])),
    );

    render(<IncomePage />);

    const subtitulo = await screen.findByText(/Suas entradas do mês/);
    expect(subtitulo.textContent).toMatch(/total R\$\s14\.941,60/);
  });
});
