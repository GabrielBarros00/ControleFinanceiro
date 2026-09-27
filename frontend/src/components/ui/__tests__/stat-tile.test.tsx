import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { StatTile } from '../stat-tile';
import { Progress } from '../progress';

/*
 * O número do card responde à largura DO CARD (container query), não à da tela
 * (auditoria 2026-09-26, C8): numa grade de quatro colunas ao lado da barra
 * lateral, o `sm:text-2xl` fixo de antes fazia "−R$ 1.617.821,75" passar da
 * borda. O jsdom não calcula container query; o que se testa aqui é a regra
 * escolhida para cada comprimento — o efeito na tela é medido pela varredura de
 * larguras do e2e.
 */
describe('StatTile', () => {
  const classesDoNumero = (valor: number, kind: 'expense' | 'income' | 'neutral' = 'neutral') => {
    render(<StatTile label="Rótulo" value={valor} kind={kind} />);
    return screen.getByText((_, el) => el?.tagName === 'SPAN' && /R\$/.test(el.textContent ?? '') && el.children.length === 0).className;
  };

  it('é um container, e o número não tem tamanho fixo por largura de TELA', () => {
    const { container } = render(<StatTile label="Saldo" value={10} />);
    expect(container.firstElementChild?.className).toContain('@container');
    expect(container.innerHTML).not.toContain('sm:text-2xl');
  });

  it('número curto: grande assim que o card tem 10,5rem', () => {
    expect(classesDoNumero(31941.39)).toContain('@min-[10.5rem]:text-2xl');
  });

  it('número longo começa pequeno (celular) e cresce com o card', () => {
    // "−R$ 1.617.821,75": 16 caracteres, o caso que vazava a 1024px.
    const classes = classesDoNumero(1617821.75, 'expense');
    expect(classes).toContain('text-sm');
    expect(classes).toContain('@min-[14.5rem]:text-2xl');
    expect(classes).not.toContain('@min-[10.5rem]:text-2xl');
  });

  it('o hint aceita conteúdo em bloco sem gerar HTML inválido', () => {
    // Financiamentos passa uma barra de progresso (div) como hint; dentro de
    // um <p> ela era HTML inválido e o React acusava a cada carga da tela.
    const { container } = render(
      <StatTile label="Saldo devedor" value={100} hint={<Progress value={40} />} />,
    );
    expect(container.querySelector('p div')).toBeNull();
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
  });
});

describe('Progress', () => {
  it('diz o valor ao leitor de tela, não "indeterminado"', () => {
    render(<Progress value={40} />);
    const barra = screen.getByRole('progressbar');
    expect(barra).toHaveAttribute('aria-valuenow', '40');
    expect(barra).toHaveAttribute('data-state', 'loading');
  });
});
