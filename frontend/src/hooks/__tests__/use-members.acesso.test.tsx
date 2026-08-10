import React from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { describe, it, expect, beforeEach } from 'vitest';
import { server } from '@/test/setup';
import { useUIStore } from '@/stores';
import { useMembers } from '../use-members';

/**
 * O CORPO do PATCH de membro, não o que o hook aceita.
 *
 * O defeito: papel e visibilidade financeira são eixos separados (ADR 0018), mas
 * havia uma mutação só, com os dois campos opcionais. A tela de membros passava,
 * ao trocar o PAPEL, o `financial_access` que tinha em mãos — que é o acesso
 * EFETIVO devolvido pela API, sempre `full_workspace` para admin. Rebaixar um
 * admin para Membro gravava "vê todo o workspace" em quem estava como "só o que
 * o envolve": tirar privilégio AMPLIAVA a visão, sem ninguém escolher isso.
 *
 * O backend fecha a visibilidade quando o campo vem ausente, então o que se mede
 * aqui é justamente a ausência dele na rede — a asserção só é possível nesta
 * camada.
 */
const WS = 7;

const wrapper = ({ children }: { children: React.ReactNode }) => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </MemoryRouter>
  );
};

function capturarPatch() {
  const corpo: { valor: Record<string, unknown> | null } = { valor: null };
  server.use(
    http.patch(`http://localhost:8000/api/v1/workspaces/${WS}/members/:userId`, async ({ request }) => {
      corpo.valor = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json({ user_id: 2, role: 'member', financial_access: 'involved_only' });
    }),
  );
  return corpo;
}

describe('useMembers — os dois eixos do PATCH de membro', () => {
  beforeEach(() => {
    useUIStore.setState({ currentWorkspaceId: WS });
  });

  it('trocar o papel NÃO manda financial_access', async () => {
    const corpo = capturarPatch();
    const { result } = renderHook(() => useMembers(), { wrapper });

    await result.current.updateMemberRole({ userId: 2, role: 'member' });

    await waitFor(() => expect(corpo.valor).not.toBeNull());
    expect(corpo.valor).toEqual({ role: 'member' });
    // O sintoma exato: com o campo presente, o rebaixamento gravava o efetivo.
    expect(corpo.valor).not.toHaveProperty('financial_access');
  });

  it('trocar a visibilidade manda os dois (o papel é obrigatório no schema)', async () => {
    const corpo = capturarPatch();
    const { result } = renderHook(() => useMembers(), { wrapper });

    await result.current.updateMemberAccess({
      userId: 2,
      role: 'member',
      financial_access: 'full_workspace',
    });

    await waitFor(() => expect(corpo.valor).not.toBeNull());
    expect(corpo.valor).toEqual({ role: 'member', financial_access: 'full_workspace' });
  });
});
