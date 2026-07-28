import { describe, expect, it } from 'vitest';
import { formatCurrency, maskCurrency, formatMoney } from '@/lib/money';

/*
 * Armadilhas numéricas corrigidas na Onda E.
 *
 * `formatCurrency` lia string como CENTAVOS (`replace(/\D/g,'')`), o que
 * descartava o sinal e interpretava "1234.5" como R$ 123,45. Nenhum call-site
 * passava string crua, mas a armadilha estava armada para o próximo.
 */
describe('formatCurrency com string', () => {
  it('preserva o sinal negativo', () => {
    expect(formatCurrency('-50.00')).toContain('50,00');
    expect(formatCurrency('-50.00')).toMatch(/-|−/);
  });

  it('lê string como decimal, não como centavos', () => {
    expect(formatCurrency('1234.5')).toContain('1.234,50');
    expect(formatCurrency('435.90')).toContain('435,90');
  });

  it('concorda com formatMoney para o mesmo valor', () => {
    const comoString = formatCurrency('435.90').replace(/\s/g, ' ');
    const comoNumero = formatCurrency(435.9).replace(/\s/g, ' ');
    expect(comoString).toBe(comoNumero);
  });
});

describe('maskCurrency', () => {
  it('limita os dígitos para não perder precisão no parseInt', () => {
    // 20 dígitos passam de Number.MAX_SAFE_INTEGER: sem o corte, o valor
    // enviado deixava de ser o digitado, em silêncio.
    const mascarado = maskCurrency('9'.repeat(20));
    const digitos = mascarado.replace(/\D/g, '');
    expect(digitos.length).toBeLessThanOrEqual(15);
  });

  it('mantém o comportamento normal de centavos', () => {
    expect(maskCurrency('12345')).toBe('123,45');
  });
});

describe('formatMoney', () => {
  it('respeita a moeda informada (moeda-base do workspace)', () => {
    expect(formatMoney(10, { currency: 'USD' })).toContain('US$');
    expect(formatMoney(10, { currency: 'BRL' })).toContain('R$');
  });
});
