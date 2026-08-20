import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { BalanceOrigin } from '../BalanceOrigin';
import type { DebtsByMonth } from '@/hooks/use-debts-by-month';

/**
 * A quebra do saldo — o bloco que responde "preciso pagar tudo isso agora?".
 *
 * O que estes casos travam é a única promessa que ele faz: **as linhas somam o
 * total**. Uma quebra que não fecha é pior do que não existir — a pessoa deixa
 * de confiar nos dois números em vez de continuar sem o segundo. Por isso os
 * casos aqui são justamente os que a página não exercita: meses agrupados,
 * acerto sem mês, saldo zero, lista vazia.
 */
const base: DebtsByMonth = {
  base_currency: 'BRL',
  balance: '-320.00',
  months: [
    { month: '2026-08', balance: '-200.00', net_debts: [], settled: '0.00' },
    { month: '2026-07', balance: '-120.00', net_debts: [], settled: '0.00' },
  ],
  older: { count: 0, balance: '0.00' },
  unassigned: '0.00',
};

function montar(origem: Partial<DebtsByMonth> = {}, onOpenMonth = vi.fn()) {
  render(
    <BalanceOrigin origem={{ ...base, ...origem }} currency="BRL" onOpenMonth={onOpenMonth} />,
  );
  return onOpenMonth;
}

describe('De onde vem esse saldo', () => {
  it('soma as linhas no total, com a direção escrita em cada uma', () => {
    montar();
    expect(screen.getByText('ago/2026')).toBeInTheDocument();
    expect(screen.getByText('você deve R$ 200,00')).toBeInTheDocument();
    expect(screen.getByText('jul/2026')).toBeInTheDocument();
    expect(screen.getByText('você deve R$ 120,00')).toBeInTheDocument();
    expect(screen.getByText('Total acumulado')).toBeInTheDocument();
    expect(screen.getByText('você deve R$ 320,00')).toBeInTheDocument();
  });

  /*
   * O mês com sinal invertido é a razão de `balance` vir com sinal em vez de dois
   * campos: devo agosto e tenho julho a receber ao mesmo tempo, e a soma dos
   * dois é o que sobra.
   */
  it('mês a receber aparece com a direção invertida e entra na soma', () => {
    montar({
      balance: '-80.00',
      months: [
        { month: '2026-08', balance: '-200.00', net_debts: [], settled: '0.00' },
        { month: '2026-07', balance: '120.00', net_debts: [], settled: '0.00' },
      ],
    });
    expect(screen.getByText('você recebe R$ 120,00')).toBeInTheDocument();
    expect(screen.getByText('você deve R$ 80,00')).toBeInTheDocument();
  });

  /*
   * O acerto registrado a partir do acumulado não carrega mês: derruba o total
   * sem fechar mês nenhum. Antes isso não aparecia em lugar nenhum, e o saldo
   * caía "sozinho" — foi a queixa que trouxe esta linha à tela.
   */
  it('mostra o acerto sem mês como linha própria', () => {
    montar({ balance: '-270.00', unassigned: '50.00' });
    expect(screen.getByText('Acertos sem mês')).toBeInTheDocument();
    expect(screen.getByText(/registrados sobre o acumulado/)).toBeInTheDocument();
    expect(screen.getByText('você recebe R$ 50,00')).toBeInTheDocument();
    expect(screen.getByText('você deve R$ 270,00')).toBeInTheDocument();
  });

  it('não inventa a linha "sem mês" quando ela é zero', () => {
    montar();
    expect(screen.queryByText('Acertos sem mês')).not.toBeInTheDocument();
  });

  /*
   * Truncar em silêncio devolveria um total que não bate com as linhas — o
   * defeito mais convincente possível, porque os dois números continuam
   * plausíveis. Os meses além do teto viram UMA linha somada.
   */
  it('agrupa os meses antigos em vez de sumir com eles', () => {
    montar({
      balance: '-500.00',
      older: { count: 3, balance: '-180.00' },
    });
    expect(screen.getByText('3 meses mais antigos')).toBeInTheDocument();
    expect(screen.getByText('você deve R$ 180,00')).toBeInTheDocument();
    expect(screen.getByText('você deve R$ 500,00')).toBeInTheDocument();
  });

  it('escreve "mês" no singular quando é um só', () => {
    montar({ older: { count: 1, balance: '-10.00' } });
    expect(screen.getByText('1 mês mais antigo')).toBeInTheDocument();
  });

  it('sem nenhum mês nem acerto solto, diz que não há mês em aberto', () => {
    montar({ balance: '0.00', months: [], older: { count: 0, balance: '0.00' }, unassigned: '0.00' });
    expect(screen.getByText('Nenhum mês em aberto.')).toBeInTheDocument();
    expect(screen.queryByText('Total acumulado')).not.toBeInTheDocument();
  });

  it('cada mês é clicável e devolve o mês, não o rótulo', () => {
    const onOpenMonth = montar();
    fireEvent.click(screen.getByText('jul/2026'));
    expect(onOpenMonth).toHaveBeenCalledWith('2026-07');
  });

  it('o mês parcialmente acertado diz quanto já foi', () => {
    montar({
      months: [{ month: '2026-08', balance: '-200.00', net_debts: [], settled: '75.00' }],
      balance: '-200.00',
    });
    expect(screen.getByText('R$ 75,00 já acertados')).toBeInTheDocument();
  });

  /* O rótulo do mês precisa do ANO: a origem de um saldo atravessa o ano, e duas
     linhas "ago" seriam indistinguíveis num lugar cujo ponto é dizer de quando
     vem a dívida. */
  it('o rótulo do mês leva o ano', () => {
    montar({
      months: [
        { month: '2026-08', balance: '-10.00', net_debts: [], settled: '0.00' },
        { month: '2025-08', balance: '-10.00', net_debts: [], settled: '0.00' },
      ],
      balance: '-20.00',
    });
    expect(screen.getByText('ago/2026')).toBeInTheDocument();
    expect(screen.getByText('ago/2025')).toBeInTheDocument();
  });
});
