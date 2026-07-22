import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { MoneyText } from '../MoneyText';

const NBSP = String.fromCharCode(160);
const MINUS = String.fromCharCode(0x2212);
const norm = (s: string) => s.split(NBSP).join(' ');

describe('MoneyText', () => {
  it('despesa: cor de expense e menos tipográfico', () => {
    const { container } = render(<MoneyText value={80} kind="expense" />);
    const el = container.firstChild as HTMLElement;
    expect(el).toHaveClass('text-expense');
    expect(norm(el.textContent || '')).toBe(`${MINUS}R$ 80,00`);
  });

  it('receita: cor de income e sinal +', () => {
    const { container } = render(<MoneyText value={80} kind="income" />);
    const el = container.firstChild as HTMLElement;
    expect(el).toHaveClass('text-income');
    expect(norm(el.textContent || '')).toBe('+R$ 80,00');
  });

  it('neutral: sem cor semântica, sem sinal', () => {
    const { container } = render(<MoneyText value={80} kind="neutral" />);
    const el = container.firstChild as HTMLElement;
    expect(el).toHaveClass('text-foreground');
    expect(el.textContent).not.toContain('+');
    expect(el.textContent).not.toContain(MINUS);
  });

  it('colorize=false remove a cor semântica', () => {
    const { container } = render(<MoneyText value={80} kind="expense" colorize={false} />);
    expect(container.firstChild as HTMLElement).not.toHaveClass('text-expense');
  });

  it('aceita string decimal da API', () => {
    const { container } = render(<MoneyText value="435.90" kind="expense" />);
    expect(norm((container.firstChild as HTMLElement).textContent || '')).toBe(`${MINUS}R$ 435,90`);
  });
});
