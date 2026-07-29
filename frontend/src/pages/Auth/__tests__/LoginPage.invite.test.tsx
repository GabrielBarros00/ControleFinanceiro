import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { LoginPage } from '../LoginPage';

vi.mock('@/hooks/use-auth', () => ({
  useAuth: () => ({ login: vi.fn() }),
}));

/**
 * Convite POR LINK para quem ainda NÃO tem conta.
 *
 * `/invite/<token>` é rota protegida: sem sessão, o app manda para `/login`
 * guardando a origem em `location.state.from`. Só que quem não tem conta segue
 * por "Cadastre-se" — e o link ia para `/register` puro. O token morria ali: a
 * pessoa se cadastrava, caía no próprio workspace e não virava membro de nada,
 * porque `?invite=` é o que o backend lê como CONSENTIMENTO no /auth/register.
 */
function renderLogin(state?: { from?: string }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[{ pathname: '/login', state }]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('LoginPage — convite por link', () => {
  it('leva o token do convite para o cadastro', () => {
    renderLogin({ from: '/invite/tok-abc123' });
    expect(screen.getByRole('link', { name: /cadastre-se/i })).toHaveAttribute(
      'href',
      '/register?invite=tok-abc123',
    );
  });

  it('sem convite, o cadastro continua limpo', () => {
    renderLogin();
    expect(screen.getByRole('link', { name: /cadastre-se/i })).toHaveAttribute(
      'href',
      '/register',
    );
  });

  it('ignora uma origem que não é convite', () => {
    renderLogin({ from: '/transactions?month=2026-07' });
    expect(screen.getByRole('link', { name: /cadastre-se/i })).toHaveAttribute(
      'href',
      '/register',
    );
  });
});
