import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@/test/utils';
import { BuscaGlobal } from '../BuscaGlobal';

/**
 * Busca global — o que a tela precisa acertar.
 *
 * A visibilidade (ADR 0018) é decidida e trancada no BACKEND
 * (`tests/security/test_busca_respeita_visibilidade.py`, escrito antes da rota).
 * Aqui o assunto é o que só o navegador vê:
 *
 * 1. A consulta **não sai a cada tecla** — "dentista" são oito requisições se
 *    ninguém segurar, e a lista de lançamentos já tinha aprendido isso.
 * 2. Termo curto **não bate no servidor**: o backend recusa com 422, e mandar
 *    para ouvir "não" é gastar viagem.
 * 3. Fechar **esquece**: reabrir com o resultado anterior faz parecer que a
 *    busca já rodou para o que se vai digitar agora.
 * 4. Cada linha **leva** a algum lugar — uma busca que acha e não leva não
 *    resolve nada.
 */
const RESULTADO = {
  query: 'dentista',
  total: 1,
  groups: [
    {
      kind: 'transaction',
      label: 'Lançamentos',
      items: [
        {
          kind: 'transaction', id: 7, title: 'Dentista da Ana',
          amount: '380.00', currency: 'BRL', occurred_on: '2026-09-01',
          workspace_id: 3, workspace_name: 'Casa',
          href: '/w/3/transactions?q=Dentista da Ana',
        },
      ],
    },
  ],
};

const get = vi.hoisted(() => vi.fn());
const navigate = vi.hoisted(() => vi.fn());

vi.mock('@/api/client', () => ({ apiClient: { get: (...a: unknown[]) => get(...a) } }));
vi.mock('react-router-dom', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  useNavigate: () => navigate,
}));

beforeEach(() => {
  get.mockReset();
  navigate.mockReset();
  get.mockResolvedValue({ data: RESULTADO });
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

const abrir = () => render(<BuscaGlobal open onOpenChange={vi.fn()} />);

describe('Busca global', () => {
  it('não consulta o servidor com uma letra só', async () => {
    abrir();
    fireEvent.change(screen.getByLabelText('Buscar em tudo'), { target: { value: 'd' } });
    await vi.advanceTimersByTimeAsync(600);

    expect(get).not.toHaveBeenCalled();
    expect(screen.getByText('Digite pelo menos duas letras.')).toBeInTheDocument();
  });

  it('espera a digitação parar antes de consultar', async () => {
    abrir();
    const campo = screen.getByLabelText('Buscar em tudo');

    for (const texto of ['de', 'den', 'dent', 'denti']) {
      fireEvent.change(campo, { target: { value: texto } });
      await vi.advanceTimersByTimeAsync(50);
    }
    expect(get, 'consultou no meio da digitação').not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(400);
    await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
    expect(get).toHaveBeenCalledWith('/me/search', { params: { q: 'denti' } });
  });

  it('agrupa os resultados pelo nome que a pessoa reconhece', async () => {
    abrir();
    fireEvent.change(screen.getByLabelText('Buscar em tudo'), { target: { value: 'dentista' } });
    await vi.advanceTimersByTimeAsync(400);

    await waitFor(() => expect(screen.getByText('Dentista da Ana')).toBeInTheDocument());
    expect(screen.getByText('Lançamentos')).toBeInTheDocument();
    // O espaço e o valor entram na linha: sem eles, dois "Mercado" de espaços
    // diferentes são indistinguíveis.
    expect(screen.getByText(/Casa/)).toBeInTheDocument();
    expect(screen.getByText('R$ 380,00')).toBeInTheDocument();
  });

  it('a linha leva ao lugar onde o item vive', async () => {
    abrir();
    fireEvent.change(screen.getByLabelText('Buscar em tudo'), { target: { value: 'dentista' } });
    await vi.advanceTimersByTimeAsync(400);
    await waitFor(() => expect(screen.getByText('Dentista da Ana')).toBeInTheDocument());

    fireEvent.click(screen.getByText('Dentista da Ana'));

    // O destino vem do SERVIDOR (`href`): é ele que sabe em qual espaço o
    // lançamento está.
    expect(navigate).toHaveBeenCalledWith('/w/3/transactions?q=Dentista da Ana');
  });

  it('diz que não achou, em vez de mostrar uma lista vazia', async () => {
    get.mockResolvedValue({ data: { query: 'xyz', total: 0, groups: [] } });
    abrir();
    fireEvent.change(screen.getByLabelText('Buscar em tudo'), { target: { value: 'xyz' } });
    await vi.advanceTimersByTimeAsync(400);

    await waitFor(() =>
      expect(screen.getByText(/Nada encontrado para "xyz"/)).toBeInTheDocument());
  });
});
