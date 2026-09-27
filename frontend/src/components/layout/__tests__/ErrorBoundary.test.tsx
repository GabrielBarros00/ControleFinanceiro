import * as React from 'react';
import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ErrorBoundary } from '../ErrorBoundary';

function Quebra({ erro }: { erro: Error }): React.ReactNode {
  throw erro;
}

describe('ErrorBoundary (C6)', () => {
  // O React registra no console todo erro capturado por um boundary. É o
  // comportamento esperado aqui, e o ruído esconderia um aviso de verdade.
  let consoleError: ReturnType<typeof vi.spyOn>;
  beforeEach(() => {
    consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
  });
  afterEach(() => {
    consoleError.mockRestore();
  });

  it('o chunk de uma tela que não baixa vira a tela de erro com "Recarregar", não tela branca', async () => {
    // O caminho real: `React.lazy` cujo `import()` falha, como acontece com a
    // aba aberta durante um deploy.
    const TelaQueSumiu = React.lazy(() =>
      Promise.reject(new TypeError('Failed to fetch dynamically imported module: http://app/assets/SettingsPage-deadbeef.js')),
    );
    const { container } = render(
      <ErrorBoundary>
        <React.Suspense fallback={<p>carregando</p>}>
          <TelaQueSumiu />
        </React.Suspense>
      </ErrorBoundary>,
    );

    expect(await screen.findByText('O app foi atualizado')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Recarregar' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Ir para o início' })).toHaveAttribute('href', '/overview');
    expect(container.textContent?.trim().length).toBeGreaterThan(0);
  });

  it('HTML servido no lugar do JS também é falha de carregamento', () => {
    render(
      <ErrorBoundary>
        <Quebra erro={new TypeError('Failed to load module script: Expected a JavaScript-or-Wasm module script but the server responded with a MIME type of "text/html".')} />
      </ErrorBoundary>,
    );
    expect(screen.getByText('O app foi atualizado')).toBeInTheDocument();
  });

  it('erro de renderização comum diz que a tela não abriu', () => {
    render(
      <ErrorBoundary>
        <Quebra erro={new Error('x is undefined')} />
      </ErrorBoundary>,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Esta tela não abriu');
    expect(screen.getByRole('button', { name: 'Recarregar' })).toBeInTheDocument();
  });

  it('mudar de caminho sai da tela de erro sem recarregar', () => {
    const { rerender } = render(
      <ErrorBoundary resetKey="/me/settings">
        <Quebra erro={new Error('quebrou')} />
      </ErrorBoundary>,
    );
    expect(screen.getByRole('alert')).toBeInTheDocument();

    rerender(
      <ErrorBoundary resetKey="/overview">
        <p>Início</p>
      </ErrorBoundary>,
    );
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getByText('Início')).toBeInTheDocument();
  });

  it('sem erro, só mostra os filhos', () => {
    render(
      <ErrorBoundary>
        <p>conteúdo</p>
      </ErrorBoundary>,
    );
    expect(screen.getByText('conteúdo')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
