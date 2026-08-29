import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MonthlyLedgerTotals, type LedgerLike } from '../MonthlyLedgerBody';

/**
 * O quadro do mês, na aba "Por mês" dos dois Acertos.
 *
 * A queixa que originou a mudança: num mês de R$ 231,47 rateado a dois, a
 * primeira coisa da tela era "TOTAL DO MÊS R$ 231,47 / EM ABERTO R$ 231,47", e
 * logo abaixo "Maria deve R$ 115,73 a você". Os dois números grandes não eram de
 * ninguém — eram o valor cheio dos lançamentos —, e o que se lê ali é que há
 * 231 a acertar.
 *
 * O que estes casos travam é que o quadro fale de QUEM OLHA, e que os números
 * dele não contradigam as linhas logo abaixo.
 */
const BASE: LedgerLike = {
  members: [
    { user_id: 1, paid: '231.47', owed: '115.74' },
    { user_id: 2, paid: '0.00', owed: '115.73' },
  ],
  net_debts: [{ debtor_id: 2, creditor_id: 1, amount: '115.73' }],
  expenses: [],
  settled_total: '0.00',
  settlements: [],
  totals: { total: '231.47', paid: '0.00', open: '231.47' },
};

const montar = (ledger: LedgerLike, currentUserId?: number) =>
  render(<MonthlyLedgerTotals ledger={ledger} currency="BRL" currentUserId={currentUserId} />);

describe('MonthlyLedgerTotals', () => {
  it('mostra a parte, o adiantado e o saldo de quem olha — não o total dos lançamentos', () => {
    montar(BASE, 1);

    expect(screen.getByText('Sua parte')).toBeInTheDocument();
    expect(screen.getByText('R$ 115,74')).toBeInTheDocument();
    expect(screen.getByText('Você pagou')).toBeInTheDocument();
    // O saldo bate com a linha "Maria deve R$ 115,73 a você" logo abaixo.
    expect(screen.getByText('Você tem a receber')).toBeInTheDocument();
    expect(screen.getByText('R$ 115,73')).toBeInTheDocument();

    // O valor cheio saiu do destaque, mas não da tela: some-lo faria a soma das
    // despesas logo abaixo não ter de onde sair.
    expect(screen.queryByText('Total do mês')).not.toBeInTheDocument();
    expect(screen.getByText(/somam R\$ 231,47 no espaço/)).toBeInTheDocument();
  });

  it('inverte o rótulo para quem deve', () => {
    montar(BASE, 2);
    expect(screen.getByText('Você deve')).toBeInTheDocument();
    // Duas vezes de propósito: a parte da Maria é 115,73 e ela deve exatamente
    // isso, porque não adiantou nada.
    expect(screen.getAllByText('R$ 115,73')).toHaveLength(2);
    expect(screen.queryByText('Você tem a receber')).not.toBeInTheDocument();
  });

  /*
   * O payload traz `members[].balance`, que é `pago − parte` calculado ANTES dos
   * acertos do mês. Usá-lo aqui poria "Você tem a receber R$ 115,73" ao lado do
   * "Tudo acertado ✅" que o corpo desenha a partir de `net_debts` — dois
   * números que se contradizem na mesma dobra.
   */
  it('mês quitado zera o saldo, mesmo com parte e adiantado intactos', () => {
    montar(
      { ...BASE, net_debts: [], settled_total: '115.73' },
      1,
    );
    expect(screen.getByText('A acertar')).toBeInTheDocument();
    expect(screen.getByText('R$ 0,00')).toBeInTheDocument();
    expect(screen.queryByText('Você tem a receber')).not.toBeInTheDocument();
    // A parte e o adiantado continuam sendo o retrato do mês.
    expect(screen.getByText('R$ 115,74')).toBeInTheDocument();
    expect(screen.getByText('R$ 231,47')).toBeInTheDocument();
  });

  /* Sem saber quem olha não existe "sua parte": anunciar R$ 0,00 como fatia de
     alguém seria pior que mostrar o retrato da casa. */
  it('sem usuário conhecido, volta ao retrato da casa em vez de inventar uma parte', () => {
    montar(BASE, undefined);
    expect(screen.getByText('Total do mês')).toBeInTheDocument();
    expect(screen.getByText('Em aberto')).toBeInTheDocument();
    expect(screen.queryByText('Sua parte')).not.toBeInTheDocument();
  });

  /*
   * Quem tem acesso financeiro completo pode abrir o mês de uma casa em que não
   * entrou em despesa nenhuma. O quadro pessoal seria "R$ 0,00 / R$ 0,00 /
   * R$ 0,00" — três zeros verdadeiros e inúteis, com o único número que diz
   * algo (o da casa) rebaixado à legenda.
   */
  it('quem não entrou no mês vê o retrato da casa, não três zeros', () => {
    montar(BASE, 99);
    expect(screen.getByText('Total do mês')).toBeInTheDocument();
    // Duas vezes: nada foi pago, então "total" e "em aberto" coincidem.
    expect(screen.getAllByText('R$ 231,47')).toHaveLength(2);
    expect(screen.queryByText('Sua parte')).not.toBeInTheDocument();
  });

  /* Mas participar com saldo zerado NÃO é o mesmo que estar fora: a parte
     continua sendo consumo, e acerto nenhum a reduz. */
  it('quem participou e está quitado continua vendo a própria leitura', () => {
    montar({ ...BASE, net_debts: [], settled_total: '115.73' }, 2);
    expect(screen.getByText('Sua parte')).toBeInTheDocument();
    expect(screen.getByText('A acertar')).toBeInTheDocument();
    expect(screen.queryByText('Total do mês')).not.toBeInTheDocument();
  });
});
