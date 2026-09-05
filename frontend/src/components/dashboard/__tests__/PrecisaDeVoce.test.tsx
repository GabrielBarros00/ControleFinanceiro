import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { PrecisaDeVoce } from '../PrecisaDeVoce';

/**
 * "Precisa de você" — o bloco que faltava na primeira tela.
 *
 * A tela anterior tinha catorze números e nenhum botão: ela descrevia a
 * situação e deixava a pessoa procurar sozinha em qual das quatro telas de
 * dívida resolver o que acabara de ler. Este bloco existe para responder "o que
 * eu preciso fazer" e permitir fazê-lo ali mesmo.
 *
 * Os três limites que este arquivo tranca:
 *
 * 1. **O recorte é prazo curto.** Vencido e vencendo em até 7 dias. Trazer tudo
 *    o que se deve transformaria o bloco noutra tela de Contas a pagar.
 * 2. **Vazio é uma resposta, não ausência.** "Tudo em dia" é dito. Um bloco que
 *    some quando não há nada é indistinguível de um bloco que não carregou.
 * 3. **Fatura e financiamento não ganham botão.** Eles não têm liquidação
 *    própria (ADR 0029) — pagar uma fatura é escolher conta e valor, o que é uma
 *    decisão e não um toque. Entram como caminho.
 */
const emDias = (offset: number) => {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  // `toISOString()` é UTC: às 22h em UTC-3 ele já devolve o dia SEGUINTE, e um
  // teste que fala em "hoje" passa a falar de amanhã dependendo da hora em que
  // roda. Aqui a data é montada em campo local, que é o que `parseApiDay` lê.
  const mes = String(d.getMonth() + 1).padStart(2, '0');
  const dia = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${mes}-${dia}`;
};

const conta = (id: number, titulo: string, dias: number) => ({
  transaction_id: id,
  workspace_id: 1,
  workspace_name: 'Casa',
  title: titulo,
  due_date: emDias(dias),
  billing_month: '2026-09',
  amount: '250.00',
  currency: 'BRL',
  converted_amount: '250.00',
  payment_method: 'pix',
  is_overdue: dias < 0,
  status: dias < 0 ? 'overdue' : dias === 0 ? 'due_today' : 'upcoming',
});

const SALDO = {
  currency: 'BRL',
  overdue_total: '0.00',
  breakdown: [] as { kind: string; label: string; amount: string; count: number }[],
};

const mockPayables = vi.hoisted(() => vi.fn());
const mockSettle = vi.hoisted(() => vi.fn());

vi.mock('@/hooks/use-payables', () => ({
  useMyPayables: () => mockPayables(),
  useSettlePayables: () => ({ settle: mockSettle, isSettling: false }),
}));

const desenhar = (saldo: unknown = SALDO) => render(
  <MemoryRouter>
    <PrecisaDeVoce month="2026-09" balance={saldo as never} />
  </MemoryRouter>,
);

beforeEach(() => {
  mockSettle.mockReset();
  mockSettle.mockResolvedValue({ updated: 1 });
  mockPayables.mockReturnValue({
    payables: { currency: 'BRL', month: '2026-09', entries: [], upcoming: [] },
    isLoading: false,
  });
});

describe('Precisa de você', () => {
  it('diz "tudo em dia" em vez de sumir quando não há nada', () => {
    desenhar();
    expect(screen.getByText('Tudo em dia')).toBeInTheDocument();
  });

  it('lista o que vence em até 7 dias e ignora o que é para depois', () => {
    mockPayables.mockReturnValue({
      payables: {
        currency: 'BRL', month: '2026-09',
        entries: [conta(1, 'Luz', -2), conta(2, 'Internet', 3)],
        upcoming: [conta(3, 'Aluguel do mês que vem', 34)],
      },
      isLoading: false,
    });
    desenhar();

    const lista = screen.getByRole('list', { name: /prazo curto/i });
    expect(within(lista).getByText('Luz')).toBeInTheDocument();
    expect(within(lista).getByText('Internet')).toBeInTheDocument();
    expect(within(lista).queryByText('Aluguel do mês que vem')).toBeNull();
  });

  it('fala em prazo, não em data ISO', () => {
    mockPayables.mockReturnValue({
      payables: {
        currency: 'BRL', month: '2026-09',
        entries: [conta(1, 'Luz', -2), conta(2, 'Água', 0)],
        upcoming: [],
      },
      isLoading: false,
    });
    desenhar();

    expect(screen.getByText(/venceu há 2 dias/)).toBeInTheDocument();
    expect(screen.getByText(/vence hoje/)).toBeInTheDocument();
  });

  it('paga a conta na própria linha, sem mudar de tela', async () => {
    mockPayables.mockReturnValue({
      payables: {
        currency: 'BRL', month: '2026-09',
        entries: [conta(42, 'Luz', -1)], upcoming: [],
      },
      isLoading: false,
    });
    desenhar();

    fireEvent.click(screen.getByRole('button', { name: /marcar "luz" como paga/i }));

    await waitFor(() => expect(mockSettle).toHaveBeenCalledWith({
      workspaceId: 1,
      transactionIds: [42],
      settled: true,
    }));
  });

  it('mostra o que já venceu como aviso com caminho', () => {
    desenhar({ ...SALDO, overdue_total: '1200.00' });
    expect(screen.getByText(/R\$\s*1\.200,00 já venceu/)).toBeInTheDocument();
  });

  it('fatura e financiamento aparecem como caminho, não como botão', () => {
    desenhar({
      ...SALDO,
      breakdown: [
        { kind: 'statement', label: 'Faturas de cartão', amount: '900.00', count: 1 },
        { kind: 'financing', label: 'Parcelas', amount: '3500.00', count: 1 },
      ],
    });

    expect(screen.getByText('Faturas de cartão')).toBeInTheDocument();
    // Nenhum "Pagar": liquidar fatura exige escolher conta e valor.
    expect(screen.queryByRole('button', { name: /pagar/i })).toBeNull();
  });
});
