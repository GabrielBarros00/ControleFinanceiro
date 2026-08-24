/**
 * O botão que se tranca sozinho enquanto a ação não termina.
 *
 * O defeito que originou este arquivo: "Convidar" não dava sinal nenhum de que
 * o convite estava sendo enviado. Parecia que o clique não pegou, e a pessoa
 * clicava de novo — mandando dois convites.
 *
 * A causa não era aquele botão. Os 19 hooks devolviam só `mutateAsync` e
 * jogavam fora o `isPending`, então NENHUM botão do app conseguia saber que uma
 * ação estava em voo, mesmo que quisesse. Corrigir botão por botão deixaria a
 * próxima tela nascer com o mesmo defeito, então a trava mora aqui: se o
 * `onClick` devolve uma promessa, o próprio `Button` se desabilita até ela
 * assentar.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { Button } from '../button';

function promessaControlada() {
  let resolve!: (v?: unknown) => void;
  let reject!: (e: unknown) => void;
  const promessa = new Promise((res, rej) => {
    resolve = res as (v?: unknown) => void;
    reject = rej;
  });
  return { promessa, resolve, reject };
}

describe('Button — trava enquanto a ação corre', () => {
  it('desabilita e anuncia ocupado enquanto a promessa não assenta', async () => {
    const { promessa, resolve } = promessaControlada();
    render(<Button onClick={() => promessa}>Convidar</Button>);
    const botao = screen.getByRole('button', { name: /convidar/i });

    expect(botao).not.toBeDisabled();
    fireEvent.click(botao);

    await waitFor(() => expect(botao).toBeDisabled());
    expect(botao).toHaveAttribute('aria-busy', 'true');

    resolve();
    await waitFor(() => expect(botao).not.toBeDisabled());
    expect(botao).not.toHaveAttribute('aria-busy', 'true');
  });

  it('o segundo clique não dispara a ação de novo', async () => {
    const { promessa, resolve } = promessaControlada();
    const acao = vi.fn(() => promessa);
    render(<Button onClick={acao}>Convidar</Button>);
    const botao = screen.getByRole('button', { name: /convidar/i });

    fireEvent.click(botao);
    fireEvent.click(botao);
    fireEvent.click(botao);

    expect(acao).toHaveBeenCalledTimes(1);
    resolve();
    await waitFor(() => expect(botao).not.toBeDisabled());
  });

  it('destrava quando a ação FALHA — senão o botão morre para sempre', async () => {
    const { promessa, reject } = promessaControlada();
    render(<Button onClick={() => promessa}>Salvar</Button>);
    const botao = screen.getByRole('button', { name: /salvar/i });

    fireEvent.click(botao);
    await waitFor(() => expect(botao).toBeDisabled());

    reject(new Error('500'));
    await waitFor(() => expect(botao).not.toBeDisabled());
  });

  it('a rejeição continua chegando em quem chamou', async () => {
    // O `Button` observa a promessa; ele não a engole. Um `catch` do chamador
    // que parasse de rodar levaria embora o toast de erro da tela inteira.
    const erro = new Error('falhou');
    const aoFalhar = vi.fn();
    render(
      <Button onClick={() => Promise.reject(erro).catch(aoFalhar)}>Salvar</Button>,
    );

    fireEvent.click(screen.getByRole('button', { name: /salvar/i }));
    await waitFor(() => expect(aoFalhar).toHaveBeenCalledWith(erro));
  });

  it('handler síncrono não trava o botão', async () => {
    const acao = vi.fn();
    render(<Button onClick={acao}>Abrir</Button>);
    const botao = screen.getByRole('button', { name: /abrir/i });

    fireEvent.click(botao);
    fireEvent.click(botao);

    expect(acao).toHaveBeenCalledTimes(2);
    expect(botao).not.toBeDisabled();
  });

  it('a prop `pending` trava sem depender do onClick', async () => {
    // O caminho dos formulários: quem submete é o `<form>`, e o clique do botão
    // `type="submit"` não roda handler nenhum que devolva promessa.
    const acao = vi.fn();
    render(<Button pending onClick={acao}>Entrar</Button>);
    const botao = screen.getByRole('button', { name: /entrar/i });

    expect(botao).toBeDisabled();
    expect(botao).toHaveAttribute('aria-busy', 'true');
    fireEvent.click(botao);
    expect(acao).not.toHaveBeenCalled();
  });

  it('um `disabled` já existente continua valendo', async () => {
    const acao = vi.fn();
    render(<Button disabled onClick={acao}>Convidar</Button>);

    fireEvent.click(screen.getByRole('button', { name: /convidar/i }));
    expect(acao).not.toHaveBeenCalled();
  });

  it('mostra o spinner enquanto corre e some depois', async () => {
    const { promessa, resolve } = promessaControlada();
    const { container } = render(<Button onClick={() => promessa}>Salvar</Button>);

    expect(container.querySelector('.animate-spin')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /salvar/i }));
    await waitFor(() => expect(container.querySelector('.animate-spin')).not.toBeNull());

    resolve();
    await waitFor(() => expect(container.querySelector('.animate-spin')).toBeNull());
  });

  it('no botão só-de-ícone o spinner SUBSTITUI o ícone', async () => {
    const { promessa } = promessaControlada();
    const { container } = render(
      <Button size="icon" aria-label="Excluir" onClick={() => promessa}>
        <svg data-testid="icone-lixeira" />
      </Button>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Excluir' }));
    await waitFor(() => expect(container.querySelector('.animate-spin')).not.toBeNull());
    // Dois SVGs numa caixa de 32px estouram o layout.
    expect(screen.queryByTestId('icone-lixeira')).toBeNull();
  });
});
