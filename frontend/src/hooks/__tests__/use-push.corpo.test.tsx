import React from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { server } from '@/test/setup';
import { usePush } from '../use-push';

/*
 * A API recusa campo desconhecido (auditoria 2026-09-26, A1), e o `toJSON()` da
 * inscrição de push do NAVEGADOR traz `expirationTime` além de `endpoint` e
 * `keys`. Mandado cru, ativar o aviso de vencimento passaria a dar 422 — e o e2e
 * não pega, porque o navegador headless nega a permissão de notificação.
 */
describe('usePush — o corpo da inscrição', () => {
  let corpo: unknown = null;

  beforeEach(() => {
    corpo = null;
    const inscricao = {
      toJSON: () => ({
        endpoint: 'https://push.exemplo/abc',
        expirationTime: null,
        keys: { p256dh: 'chave-p256dh', auth: 'chave-auth' },
      }),
    };
    vi.stubGlobal('Notification', Object.assign(function Notification() {}, {
      permission: 'default',
      requestPermission: vi.fn(async () => 'granted'),
    }));
    vi.stubGlobal('PushManager', function PushManager() {});
    Object.defineProperty(navigator, 'serviceWorker', {
      configurable: true,
      value: {
        ready: Promise.resolve({
          pushManager: { getSubscription: async () => null, subscribe: async () => inscricao },
        }),
      },
    });
    server.use(
      http.get('http://localhost:8000/api/v1/me/push/config', () =>
        HttpResponse.json({ enabled: true, public_key: 'BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U' })),
      http.post('http://localhost:8000/api/v1/me/push/subscriptions', async ({ request }) => {
        corpo = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    Reflect.deleteProperty(navigator, 'serviceWorker');
  });

  it('manda só endpoint e keys — nunca o expirationTime do navegador', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => usePush(), { wrapper });
    // O estado vira "desativado" antes de a configuração chegar; sem a chave
    // pública, `ativar` sai cedo. Espera a configuração.
    await waitFor(() => expect(queryClient.getQueryData(['push', 'config'])).toBeTruthy());
    await waitFor(() => expect(result.current.estado).toBe('desativado'));

    let ok = false;
    await act(async () => { ok = await result.current.ativar(); });

    expect(ok).toBe(true);
    expect(corpo).toEqual({ endpoint: 'https://push.exemplo/abc', keys: { p256dh: 'chave-p256dh', auth: 'chave-auth' } });
  });
});
