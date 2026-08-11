import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';

import { navSections, navFlat, activeNavPath, PLATFORM_SECTION } from '@/components/layout/nav-items';

/*
 * Papel de plataforma na interface (ADR 0026).
 *
 * O que estes testes protegem é uma distinção que some fácil: o papel no SITE
 * (`platform_role`) e o papel no WORKSPACE (`role`) são eixos diferentes, e o
 * item "Administração" responde só ao primeiro. Confundi-los daria a um `owner`
 * de workspace — que existe em qualquer conta, porque todo mundo é dono do
 * próprio espaço — o menu de administração do servidor.
 *
 * Vale lembrar o que estes testes NÃO provam: esconder o item não é segurança.
 * Quem barra é `require_platform_role` no servidor, com 404. Aqui é só a
 * conveniência de não oferecer uma tela que só produziria erro.
 */

const estadoDeAutenticacao = { user: null as { platform_role?: string } | null };

vi.mock('@/stores', async (original) => {
  const real = await original<typeof import('@/stores')>();
  return {
    ...real,
    useAuthStore: (seletor: (s: unknown) => unknown) => seletor(estadoDeAutenticacao),
  };
});

const { useIsPlatformAdmin, useIsSuperadmin } = await import('@/hooks/use-admin');

beforeEach(() => {
  estadoDeAutenticacao.user = null;
});

describe('quem é administrador do site', () => {
  it('usuário comum não é', () => {
    estadoDeAutenticacao.user = { platform_role: 'user' };
    expect(renderHook(() => useIsPlatformAdmin()).result.current).toBe(false);
  });

  it('admin é', () => {
    estadoDeAutenticacao.user = { platform_role: 'admin' };
    expect(renderHook(() => useIsPlatformAdmin()).result.current).toBe(true);
  });

  it('superadmin é admin e superadmin', () => {
    estadoDeAutenticacao.user = { platform_role: 'superadmin' };
    expect(renderHook(() => useIsPlatformAdmin()).result.current).toBe(true);
    expect(renderHook(() => useIsSuperadmin()).result.current).toBe(true);
  });

  it('admin comum NÃO é superadmin', () => {
    estadoDeAutenticacao.user = { platform_role: 'admin' };
    expect(renderHook(() => useIsSuperadmin()).result.current).toBe(false);
  });

  it('sessão sem papel (resposta antiga do servidor) não é admin', () => {
    // Defensivo: `platform_role` é opcional no tipo, e `undefined` precisa
    // significar "sem poder", não "não sei, deixa passar".
    estadoDeAutenticacao.user = {};
    expect(renderHook(() => useIsPlatformAdmin()).result.current).toBe(false);
  });

  it('sem sessão não é admin', () => {
    expect(renderHook(() => useIsPlatformAdmin()).result.current).toBe(false);
  });
});

describe('a seção de administração na navegação', () => {
  it('não aparece para quem não tem o papel', () => {
    const rotulos = navSections(7, false).map((s) => s.label);
    expect(rotulos).not.toContain(PLATFORM_SECTION.label);
    expect(navFlat(7, false).some((i) => i.to === '/admin')).toBe(false);
  });

  it('aparece para quem tem', () => {
    expect(navFlat(7, true).some((i) => i.to === '/admin')).toBe(true);
  });

  it('aparece mesmo sem workspace selecionado', () => {
    // Administrar o site não depende de estar dentro de uma casa — e quem acabou
    // de sair do último workspace não pode perder o acesso à administração.
    expect(navFlat(null, true).some((i) => i.to === '/admin')).toBe(true);
  });

  it('o padrão do parâmetro é NÃO mostrar', () => {
    // `navSections(id)` sem o segundo argumento é como os chamadores antigos
    // ficaram. O padrão precisa ser o fechado.
    expect(navFlat(7).some((i) => i.to === '/admin')).toBe(false);
  });

  it('marca o item ativo em /admin', () => {
    expect(activeNavPath('/admin', 7, true)).toBe('/admin');
  });

  it('não confunde /admin com as rotas de workspace', () => {
    expect(activeNavPath('/w/7/settings', 7, true)).toBe('/w/7/settings');
  });
});
