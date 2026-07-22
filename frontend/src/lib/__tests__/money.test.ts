import { describe, it, expect } from 'vitest';
import { formatMoney, formatCompact } from '@/lib/money';

// Intl pt-BR usa espaço fixo (U+00A0) entre "R$" e o número; normaliza p/ comparar.
// Fonte 100% ASCII (fromCharCode) para não depender de caracteres invisíveis.
const NBSP = String.fromCharCode(160);
const MINUS = String.fromCharCode(0x2212); // menos tipográfico usado pelo formatMoney
const norm = (s: string) => s.split(NBSP).join(' ');

describe('formatMoney', () => {
  it('formata número pt-BR com 2 casas', () => {
    expect(norm(formatMoney(1234.5))).toBe('R$ 1.234,50');
  });

  it('interpreta string como DECIMAL, não centavos (corrige o bug B2)', () => {
    expect(norm(formatMoney('5449.14'))).toBe('R$ 5.449,14');
    expect(norm(formatMoney('435.9'))).toBe('R$ 435,90');
  });

  it('usa o menos tipográfico em negativos', () => {
    expect(norm(formatMoney(-80))).toBe(`${MINUS}R$ 80,00`);
  });

  it('mostra + quando sign e positivo', () => {
    expect(norm(formatMoney(80, { sign: true }))).toBe('+R$ 80,00');
    expect(norm(formatMoney(-80, { sign: true }))).toBe(`${MINUS}R$ 80,00`);
  });

  it('hideCents remove os centavos', () => {
    expect(formatMoney(1234.5, { hideCents: true })).not.toContain(',');
  });

  it('trata valor inválido como zero', () => {
    expect(norm(formatMoney(Number.NaN))).toBe('R$ 0,00');
    expect(norm(formatMoney('abc'))).toBe('R$ 0,00');
  });
});

describe('formatCompact', () => {
  it('milhares e milhões', () => {
    expect(norm(formatCompact(1200))).toBe('R$ 1,2 mil');
    expect(norm(formatCompact(3_000_000))).toBe('R$ 3 mi');
  });
  it('abaixo de mil, sem sufixo', () => {
    expect(norm(formatCompact(750))).toBe('R$ 750');
  });
});
