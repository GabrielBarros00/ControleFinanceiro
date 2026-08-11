import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as React from 'react';

/*
 * O que os hooks de administração pedem à rede, e quando.
 *
 * A propriedade mais importante aqui é o `enabled`: TODA consulta de `/admin`
 * fica desligada para quem não tem papel de plataforma. Sem esse portão, cada
 * carga de página de um usuário comum dispararia meia dúzia de requisições que
 * o servidor responde com 404 — ruído no console do navegador e ida à rede
 * garantidamente inútil. É o mesmo cuidado que `useMembers` já tem com a lista
 * de convites do workspace.
 *
 * O segundo assunto são as chaves de invalidação. Mudar um papel mexe na LISTA
 * e nos NÚMEROS do topo; invalidar só a lista deixaria os totais mentindo até o
 * próximo F5.
 */

const get = vi.fn();
const post = vi.fn();
const put = vi.fn();
const patch = vi.fn();
const del = vi.fn();

vi.mock('@/api/client', () => ({
  apiClient: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
    put: (...a: unknown[]) => put(...a),
    patch: (...a: unknown[]) => patch(...a),
    delete: (...a: unknown[]) => del(...a),
  },
}));

const sessao = { user: null as { platform_role?: string } | null };

vi.mock('@/stores', async (original) => {
  const real = await original<typeof import('@/stores')>();
  return { ...real, useAuthStore: (s: (x: unknown) => unknown) => s(sessao) };
});

const {
  useAdminOverview, useAdminSaude, useAdminUsers, useAdminSettings,
  useRegistrationInvites, useAdminAudit, useMeusConvitesDeCadastro,
} = await import('@/hooks/use-admin');

let queryClient: QueryClient;

function envolver({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  sessao.user = { platform_role: 'superadmin' };
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  get.mockResolvedValue({ data: {} });
  post.mockResolvedValue({ data: {} });
  put.mockResolvedValue({ data: {} });
  patch.mockResolvedValue({ data: {} });
  del.mockResolvedValue({ data: {} });
});

describe('o portão do `enabled`', () => {
  const consultas = [
    ['visão geral', useAdminOverview],
    ['saúde', useAdminSaude],
    ['pessoas', useAdminUsers],
    ['configurações', useAdminSettings],
    ['convites', useRegistrationInvites],
    ['auditoria', useAdminAudit],
  ] as const;

  it.each(consultas)('usuário comum não dispara a consulta de %s', async (_, hook) => {
    sessao.user = { platform_role: 'user' };
    renderHook(() => hook(), { wrapper: envolver });
    await new Promise((r) => setTimeout(r, 20));
    expect(get).not.toHaveBeenCalled();
  });

  it.each(consultas)('administrador dispara a consulta de %s', async (_, hook) => {
    sessao.user = { platform_role: 'admin' };
    renderHook(() => hook(), { wrapper: envolver });
    await waitFor(() => expect(get).toHaveBeenCalled());
  });
});

describe('endereços consultados', () => {
  it('cada hook bate no próprio endpoint', async () => {
    const casos: Array<[() => unknown, string]> = [
      [useAdminOverview, '/admin/overview'],
      [useAdminSaude, '/admin/health'],
      [useAdminUsers, '/admin/users'],
      [useAdminSettings, '/admin/settings'],
      [useRegistrationInvites, '/admin/registration-invites'],
      [useAdminAudit, '/admin/audit'],
    ];
    for (const [hook, url] of casos) {
      get.mockClear();
      renderHook(() => hook(), { wrapper: envolver });
      await waitFor(() => expect(get).toHaveBeenCalled());
      expect(get.mock.calls[0][0]).toBe(url);
    }
  });

  it('a busca de pessoas vira parâmetro, e o vazio não vira string vazia', async () => {
    // `busca: ''` na URL faria o servidor filtrar por string vazia em vez de não
    // filtrar — `undefined` é o que o axios omite.
    renderHook(() => useAdminUsers({ busca: '', offset: 0 }), { wrapper: envolver });
    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(get.mock.calls[0][1]).toEqual({ params: { busca: undefined, offset: 0 } });

    get.mockClear();
    renderHook(() => useAdminUsers({ busca: 'gabriel' }), { wrapper: envolver });
    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(get.mock.calls[0][1]).toEqual({ params: { busca: 'gabriel', offset: 0 } });
  });
});

describe('mutações', () => {
  it('alterar papel envia PATCH sem o id no corpo', async () => {
    // O `userId` vai na URL e é retirado do corpo pelo destructuring do hook.
    // Se vazasse para o corpo, o servidor o ignoraria — e um `userId` no payload
    // de um PATCH é o tipo de detalhe que alguém "corrige" um dia trocando o
    // alvo da operação.
    const { result } = renderHook(() => useAdminUsers(), { wrapper: envolver });
    await result.current.patch.mutateAsync({ userId: 7, platform_role: 'admin' });
    expect(patch).toHaveBeenCalledWith('/admin/users/7', { platform_role: 'admin' });
  });

  it('desativar e revogar sessões batem nos endpoints certos', async () => {
    const { result } = renderHook(() => useAdminUsers(), { wrapper: envolver });
    await result.current.revogarSessoes.mutateAsync(7);
    expect(post).toHaveBeenCalledWith('/admin/users/7/revoke-sessions');

    await result.current.remover.mutateAsync(7);
    expect(del).toHaveBeenCalledWith('/admin/users/7');
  });

  it('salvar configuração envolve os valores em `valores`', async () => {
    const { result } = renderHook(() => useAdminSettings(), { wrapper: envolver });
    await result.current.salvar.mutateAsync({ maintenance_mode: true });
    expect(put).toHaveBeenCalledWith('/admin/settings', {
      valores: { maintenance_mode: true },
    });
  });

  it('teste de e-mail manda o destinatário', async () => {
    const { result } = renderHook(() => useAdminSettings(), { wrapper: envolver });
    await result.current.testarEmail.mutateAsync('eu@example.com');
    expect(post).toHaveBeenCalledWith('/admin/settings/test-email', { para: 'eu@example.com' });
  });

  it('criar e revogar convite', async () => {
    const { result } = renderHook(() => useRegistrationInvites(), { wrapper: envolver });
    await result.current.criar.mutateAsync({ email: 'x@example.com' });
    expect(post).toHaveBeenCalledWith('/admin/registration-invites', { email: 'x@example.com' });

    await result.current.revogar.mutateAsync(3);
    expect(del).toHaveBeenCalledWith('/admin/registration-invites/3');
  });

  it('mutação invalida a família `admin` inteira, não só a lista', async () => {
    // Mudar um papel mexe na lista E nos números do topo.
    const invalidar = vi.spyOn(queryClient, 'invalidateQueries');
    const { result } = renderHook(() => useAdminUsers(), { wrapper: envolver });
    await result.current.revogarSessoes.mutateAsync(7);
    expect(invalidar).toHaveBeenCalledWith({ queryKey: ['admin'] });
  });
});

describe('convite emitido por usuário comum', () => {
  it('não exige papel de plataforma', async () => {
    // A rota é `/me/...`: quem já está dentro pode chamar alguém, sujeito à cota.
    sessao.user = { platform_role: 'user' };
    renderHook(() => useMeusConvitesDeCadastro(), { wrapper: envolver });
    await waitFor(() => expect(get).toHaveBeenCalledWith('/me/registration-invites'));
  });

  it('convidar bate na rota pessoal e invalida só a própria lista', async () => {
    sessao.user = { platform_role: 'user' };
    const invalidar = vi.spyOn(queryClient, 'invalidateQueries');
    const { result } = renderHook(() => useMeusConvitesDeCadastro(), { wrapper: envolver });
    await result.current.convidar.mutateAsync({ email: 'amiga@example.com' });
    expect(post).toHaveBeenCalledWith('/me/registration-invites', { email: 'amiga@example.com' });
    expect(invalidar).toHaveBeenCalledWith({ queryKey: ['me', 'registration-invites'] });
  });
});
