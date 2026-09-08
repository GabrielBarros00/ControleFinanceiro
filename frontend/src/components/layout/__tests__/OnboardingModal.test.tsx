import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { OnboardingModal } from '../OnboardingModal';

const post = vi.fn().mockResolvedValue({ data: { status: 'ok' } });

vi.mock('@/api/client', () => ({
  apiClient: { post: (...args: unknown[]) => post(...args) },
}));

vi.mock('@/hooks/use-auth', () => ({
  useAuth: () => ({ user: { id: 1, name: 'Gabriel Barros', needs_onboarding: true } }),
}));

vi.mock('@/hooks/use-base-currency', () => ({
  useBaseCurrency: () => 'USD',
}));

beforeEach(() => {
  post.mockClear();
  // handleFinish recarrega a página para reler o usuário
  Object.defineProperty(window, 'location', {
    value: { ...window.location, reload: vi.fn() },
    writable: true,
  });
});

describe('OnboardingModal', () => {
  it('é um diálogo de verdade (foco preso, role e rótulo)', () => {
    render(<OnboardingModal />);
    // Era uma <div className="fixed inset-0"> na mão: sem role, sem aria-modal,
    // sem focus trap — na PRIMEIRA tela que um usuário novo vê.
    // getByRole('dialog') já falha se não houver role — a <div> antiga não tinha.
    const dialogo = screen.getByRole('dialog');
    expect(dialogo).toHaveAccessibleName(/bem-vindo/i);
    expect(dialogo).toHaveAccessibleDescription(/controlar sua vida financeira/i);
  });

  it('bloqueia: não oferece fechar sem concluir', () => {
    render(<OnboardingModal />);
    expect(screen.queryByRole('button', { name: /close/i })).not.toBeInTheDocument();
  });

  it('não manda workspace_id — o backend resolve o workspace próprio', async () => {
    render(<OnboardingModal />);

    fireEvent.click(screen.getByRole('button', { name: /^começar$/i }));
    fireEvent.click(screen.getByRole('button', { name: /pular esta etapa/i }));

    await waitFor(() => expect(post).toHaveBeenCalled());
    const [url, payload] = post.mock.calls[0];
    expect(url).toBe('/auth/onboarding');
    // Mandar o workspace ativo gravava o salário no workspace COMPARTILHADO de
    // quem se cadastrou por convite (nasce com dois workspaces).
    expect(payload).not.toHaveProperty('workspace_id');
  });

  it('manda a conta e o saldo — o dado que a primeira tela precisa', async () => {
    render(<OnboardingModal />);

    fireEvent.click(screen.getByRole('button', { name: /^começar$/i }));
    fireEvent.change(screen.getByLabelText('Onde está o dinheiro'), {
      target: { value: 'Nubank' },
    });
    fireEvent.change(screen.getByLabelText('Quanto há nela agora'), {
      target: { value: '1.500,00' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^concluir$/i }));

    await waitFor(() => expect(post).toHaveBeenCalled());
    const [, payload] = post.mock.calls[0];
    expect(payload).toMatchObject({ account_name: 'Nubank', account_balance: 1500 });
  });

  it('sem conta informada, não inventa uma', async () => {
    // Contrapeso: "pular" tem de chegar ao servidor como pulo, e não como uma
    // conta chamada "" com saldo zero.
    render(<OnboardingModal />);
    fireEvent.click(screen.getByRole('button', { name: /^começar$/i }));
    fireEvent.click(screen.getByRole('button', { name: /pular esta etapa/i }));

    await waitFor(() => expect(post).toHaveBeenCalled());
    const [, payload] = post.mock.calls[0];
    expect(payload).toMatchObject({ account_name: null, account_balance: null });
  });
});
