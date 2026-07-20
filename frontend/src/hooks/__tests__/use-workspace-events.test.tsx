import React from 'react';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { useWorkspaceEvents, keysForEvent, wsUrl } from '../use-workspace-events';
import { useAuthStore, useUIStore } from '@/stores';

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  url: string;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  close() {
    this.closed = true;
    this.onclose?.({ code: 1000 });
  }

  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

function setup() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  const hook = renderHook(() => useWorkspaceEvents(), { wrapper });
  return { queryClient, invalidateSpy, hook };
}

describe('useWorkspaceEvents', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal('WebSocket', FakeWebSocket as unknown as typeof WebSocket);
    FakeWebSocket.instances = [];
    useAuthStore.getState().setUser({ id: 1, name: 'Tester', email: 't@t.com' });
    useUIStore.getState().setCurrentWorkspaceId(5);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    useAuthStore.getState().logout();
  });

  it('conecta na URL do workspace atual', () => {
    const { hook } = setup();
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeWebSocket.instances[0].url).toBe(wsUrl(5));
    hook.unmount();
  });

  it('evento em ordem invalida apenas as queries mapeadas', () => {
    const { invalidateSpy, hook } = setup();
    const socket = FakeWebSocket.instances[0];

    act(() => {
      socket.emit({ type: 'hello', seq: 3, workspace_id: 5 });
      socket.emit({ type: 'transaction.created', seq: 4, workspace_id: 5 });
      vi.advanceTimersByTime(300); // debounce
    });

    const calls = invalidateSpy.mock.calls;
    // Invalidação direcionada: nenhuma chamada "sem filtro" (resync total)
    expect(calls.every((c) => c[0] !== undefined)).toBe(true);
    const keys = calls.map((c) => JSON.stringify((c[0] as { queryKey: unknown }).queryKey));
    for (const expected of keysForEvent('transaction.created', 5)) {
      expect(keys).toContain(JSON.stringify(expected));
    }
    hook.unmount();
  });

  it('lacuna na sequência dispara resync completo', () => {
    const { invalidateSpy, hook } = setup();
    const socket = FakeWebSocket.instances[0];

    act(() => {
      socket.emit({ type: 'hello', seq: 3, workspace_id: 5 });
      socket.emit({ type: 'transaction.created', seq: 6, workspace_id: 5 }); // pulo: 3 → 6
      vi.advanceTimersByTime(300);
    });

    // invalidateQueries() sem argumentos = resync total
    expect(invalidateSpy.mock.calls.some((c) => c[0] === undefined)).toBe(true);
    hook.unmount();
  });

  it('hello divergente após reconexão dispara resync completo', () => {
    const { invalidateSpy, hook } = setup();
    const socket = FakeWebSocket.instances[0];

    act(() => {
      socket.emit({ type: 'hello', seq: 3, workspace_id: 5 });
      // Conexão cai (código genérico) → reconecta com backoff
      socket.onclose?.({ code: 1006 });
      vi.advanceTimersByTime(2000);
    });

    const socket2 = FakeWebSocket.instances[1];
    expect(socket2).toBeDefined();

    act(() => {
      // Enquanto offline, outros clientes fizeram 2 mutações (seq agora é 5)
      socket2.emit({ type: 'hello', seq: 5, workspace_id: 5 });
      vi.advanceTimersByTime(300);
    });

    expect(invalidateSpy.mock.calls.some((c) => c[0] === undefined)).toBe(true);
    hook.unmount();
  });

  it('fecha a conexão ao desmontar', () => {
    const { hook } = setup();
    const socket = FakeWebSocket.instances[0];
    hook.unmount();
    expect(socket.closed).toBe(true);
  });

  it('4403 não tenta reconectar', () => {
    const { hook } = setup();
    const socket = FakeWebSocket.instances[0];

    act(() => {
      socket.onclose?.({ code: 4403 });
      vi.advanceTimersByTime(60_000);
    });

    expect(FakeWebSocket.instances).toHaveLength(1);
    hook.unmount();
  });
});
