import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { BotaoAtivarNotificacoes, ConviteDeNotificacao } from '../AtivarNotificacoes';
import type { EstadoDoPush } from '@/hooks/use-push';

/*
 * O que estes testes protegem (ADR 0033).
 *
 * O erro que custa caro aqui não é visual: é oferecer "Ativar" onde ativar não
 * pode funcionar. `Notification.requestPermission()` é irreversível na prática —
 * negado, o navegador não pergunta de novo e o canal se perde. Então os dois
 * estados em que o botão precisa ENSINAR em vez de tentar (`bloqueado` e
 * `precisa-instalar`) são o coração deste arquivo.
 */

const ativar = vi.fn().mockResolvedValue(true);
let estadoAtual: EstadoDoPush = 'desativado';
let usuario: { needs_onboarding: boolean } | null = { needs_onboarding: false };

vi.mock('@/hooks/use-push', () => ({
  usePush: () => ({ estado: estadoAtual, ativar, desativar: vi.fn(), ocupado: false }),
}));

vi.mock('@/hooks/use-auth', () => ({
  useAuth: () => ({ user: usuario }),
}));

vi.mock('@/stores/toast', () => ({
  toast: { success: vi.fn(), info: vi.fn(), error: vi.fn() },
}));

beforeEach(() => {
  ativar.mockClear();
  estadoAtual = 'desativado';
  usuario = { needs_onboarding: false };
  localStorage.clear();
  vi.useRealTimers();
});

describe('BotaoAtivarNotificacoes', () => {
  it('some quando já está ativado — não há o que oferecer', () => {
    estadoAtual = 'ativado';
    const { container } = render(<BotaoAtivarNotificacoes />);
    expect(container).toBeEmptyDOMElement();
  });

  it('some quando o navegador não faz push', () => {
    estadoAtual = 'indisponivel';
    const { container } = render(<BotaoAtivarNotificacoes />);
    expect(container).toBeEmptyDOMElement();
  });

  it('pede a permissão quando dá para ativar', async () => {
    render(<BotaoAtivarNotificacoes />);
    fireEvent.click(screen.getByRole('button', { name: /ativar avisos/i }));
    await waitFor(() => expect(ativar).toHaveBeenCalledTimes(1));
  });

  it('BLOQUEADO: ensina a desbloquear em vez de tentar de novo', async () => {
    // `requestPermission()` devolveria 'denied' na hora, sem perguntar nada —
    // um botão que "não faz nada" é pior do que um que explica.
    estadoAtual = 'bloqueado';
    render(<BotaoAtivarNotificacoes />);
    fireEvent.click(screen.getByRole('button', { name: /bloqueadas/i }));

    expect(await screen.findByText(/Como desbloquear/i)).toBeInTheDocument();
    expect(ativar).not.toHaveBeenCalled();
  });

  it('iPHONE em aba: manda instalar antes, e não tenta ativar', async () => {
    // A Apple só entrega push para app da Tela de Início. Oferecer "Ativar"
    // aqui seria oferecer um botão que não pode funcionar.
    estadoAtual = 'precisa-instalar';
    render(<BotaoAtivarNotificacoes variante="faixa" />);
    fireEvent.click(screen.getByRole('button', { name: /ativar avisos/i }));

    expect(await screen.findByText(/Adicionar à Tela de Início/i)).toBeInTheDocument();
    expect(ativar).not.toHaveBeenCalled();
  });

  it('a faixa diz o porquê; o ícone se identifica por rótulo', () => {
    const { unmount } = render(<BotaoAtivarNotificacoes variante="faixa" />);
    expect(screen.getByText(/três dias antes e no dia/i)).toBeInTheDocument();
    unmount();

    render(<BotaoAtivarNotificacoes variante="icone" />);
    expect(screen.getByRole('button', { name: /ativar avisos de vencimento/i })).toBeInTheDocument();
  });
});

describe('ConviteDeNotificacao', () => {
  it('aparece explicando o benefício antes de pedir a permissão', async () => {
    render(<ConviteDeNotificacao />);
    expect(await screen.findByRole('dialog', {}, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.getByText(/Quer ser avisado antes de vencer/i)).toBeInTheDocument();
    // O prompt do navegador NÃO pode ter sido disparado só por a tela abrir.
    expect(ativar).not.toHaveBeenCalled();
  });

  it('não atropela o onboarding', async () => {
    usuario = { needs_onboarding: true };
    render(<ConviteDeNotificacao />);
    await new Promise((r) => setTimeout(r, 1400));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('não reaparece na mesma semana depois de "Agora não"', async () => {
    const { unmount } = render(<ConviteDeNotificacao />);
    // `timeout` acima do padrão de 1000ms: o convite espera 1200ms de propósito
    // antes de aparecer — o modal que salta junto com a tela é lido como pop-up
    // e fechado por reflexo.
    fireEvent.click(
      await screen.findByRole('button', { name: /agora não/i }, { timeout: 3000 }),
    );
    unmount();

    render(<ConviteDeNotificacao />);
    await new Promise((r) => setTimeout(r, 1400));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('não aparece para quem já ativou', async () => {
    estadoAtual = 'ativado';
    render(<ConviteDeNotificacao />);
    await new Promise((r) => setTimeout(r, 1400));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
