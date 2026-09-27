import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Toaster } from '../toaster';
import { toast, useToastStore } from '@/stores/toast';

/*
 * Os avisos saíram do `framer-motion` para animação em CSS (auditoria
 * 2026-09-26). O que a biblioteca fazia de graça e agora é código nosso: o aviso
 * continua na tela durante a animação de SAÍDA e só então sai da store.
 */
describe('Toaster', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    act(() => useToastStore.setState({ toasts: [] }));
    vi.useRealTimers();
  });

  it('fechar anima a saída e só então remove o aviso', () => {
    render(<Toaster />);
    act(() => { toast.success('Lançamento salvo'); });
    const aviso = screen.getByRole('status');
    expect(aviso.className).toContain('animate-in');

    fireEvent.click(screen.getByRole('button', { name: 'Fechar' }));
    // Ainda na tela, saindo.
    expect(screen.getByRole('status').className).toContain('animate-out');
    expect(useToastStore.getState().toasts).toHaveLength(1);

    act(() => { vi.advanceTimersByTime(300); });
    expect(screen.queryByRole('status')).toBeNull();
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });

  // O `onAnimationEnd` (remover assim que a saída termina) não é testável aqui:
  // o jsdom não implementa `AnimationEvent`, e o React não entrega o evento.
  // O prazo de 250 ms acima é a garantia; o atalho é conferido no navegador.

  it('some sozinho depois da duração, passando pela saída', () => {
    render(<Toaster />);
    act(() => { toast.success('Pago'); });
    const duracao = useToastStore.getState().toasts[0].duration;
    act(() => { vi.advanceTimersByTime(duracao); });
    expect(screen.getByRole('status').className).toContain('animate-out');
    act(() => { vi.advanceTimersByTime(300); });
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('a ação ("Desfazer") roda e fecha o aviso', () => {
    const desfazer = vi.fn();
    render(<Toaster />);
    act(() => { toast.comAcao('Lançamento removido', { label: 'Desfazer', onClick: desfazer }); });
    fireEvent.click(screen.getByRole('button', { name: 'Desfazer' }));
    expect(desfazer).toHaveBeenCalledTimes(1);
    act(() => { vi.advanceTimersByTime(300); });
    expect(screen.queryByRole('status')).toBeNull();
  });
});
