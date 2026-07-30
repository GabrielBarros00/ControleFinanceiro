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
      // O primeiro hello sempre ressincroniza (cache sem correlação com o seq);
      // o que este teste cobre é o evento SEGUINTE, já com marco estabelecido.
      socket.emit({ type: 'hello', seq: 3, workspace_id: 5 });
      vi.advanceTimersByTime(300);
    });
    invalidateSpy.mockClear();

    act(() => {
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

  it('primeiro hello do workspace dispara resync completo', () => {
    /* O cache é preenchido por HTTP, sem correlação nenhuma com o seq: uma
     * mutação commitada entre o GET e a entrada do socket na sala já está
     * contada no `hello.seq` mas não nos dados, e não gera lacuna depois (o
     * próximo evento chega em ordem) — ficaria invisível até um F5. Era o bug
     * da troca de workspace: socket novo recebia o hello e o lançamento do
     * outro membro nunca aparecia. */
    const { invalidateSpy, hook } = setup();
    const socket = FakeWebSocket.instances[0];

    act(() => {
      socket.emit({ type: 'hello', seq: 9, workspace_id: 5 });
      vi.advanceTimersByTime(300);
    });

    expect(invalidateSpy.mock.calls.some((c) => c[0] === undefined)).toBe(true);
    hook.unmount();
  });

  it('reconexão sem novidade (mesmo seq) NÃO ressincroniza de novo', () => {
    // Marco já estabelecido: repetir o resync a cada reconexão seria uma rajada
    // de refetch sem motivo (a tabela de ws-events chega a 12 famílias).
    const { invalidateSpy, hook } = setup();
    const socket = FakeWebSocket.instances[0];

    act(() => {
      socket.emit({ type: 'hello', seq: 3, workspace_id: 5 });
      vi.advanceTimersByTime(300);
      socket.onclose?.({ code: 1006 });
      vi.advanceTimersByTime(2000);
    });
    invalidateSpy.mockClear();

    const socket2 = FakeWebSocket.instances[1];
    act(() => {
      socket2.emit({ type: 'hello', seq: 3, workspace_id: 5 });
      vi.advanceTimersByTime(300);
    });

    expect(invalidateSpy).not.toHaveBeenCalled();
    hook.unmount();
  });

  it('troca de workspace ressincroniza o workspace novo', () => {
    const { invalidateSpy, hook } = setup();

    act(() => {
      FakeWebSocket.instances[0].emit({ type: 'hello', seq: 3, workspace_id: 5 });
      vi.advanceTimersByTime(300);
    });

    // Switcher: o hook fecha o socket antigo e abre no workspace novo
    act(() => {
      useUIStore.getState().setCurrentWorkspaceId(7);
    });
    const novo = FakeWebSocket.instances.find((s) => s.url === wsUrl(7));
    expect(novo).toBeDefined();
    invalidateSpy.mockClear();

    act(() => {
      novo!.emit({ type: 'hello', seq: 40, workspace_id: 7 });
      vi.advanceTimersByTime(300);
    });

    expect(invalidateSpy.mock.calls.some((c) => c[0] === undefined)).toBe(true);
    hook.unmount();
  });

  it('evento antes do hello não faz o marco regredir', () => {
    /* O socket entra na sala ANTES de o servidor ler o seq do `hello`, então um
     * evento publicado nesse meio pode chegar primeiro e com seq À FRENTE do
     * hello. Se o hello puxasse o marco para trás, o evento seguinte pareceria
     * lacuna e forçaria um resync total à toa. */
    const { invalidateSpy, hook } = setup();
    const socket = FakeWebSocket.instances[0];

    act(() => {
      socket.emit({ type: 'transaction.created', seq: 13, workspace_id: 5 });
      socket.emit({ type: 'hello', seq: 12, workspace_id: 5 }); // hello ficou atrás
      vi.advanceTimersByTime(300);
    });
    invalidateSpy.mockClear();

    act(() => {
      socket.emit({ type: 'transaction.created', seq: 14, workspace_id: 5 });
      vi.advanceTimersByTime(300);
    });

    // 14 = 13+1: em ordem, invalidação direcionada (nenhum resync total)
    expect(invalidateSpy).toHaveBeenCalled();
    expect(invalidateSpy.mock.calls.every((c) => c[0] !== undefined)).toBe(true);
    hook.unmount();
  });

  it('marco de conexão anterior não protege contra o hello', () => {
    /* A proteção do marco vale só para o que ESTA conexão entregou. Se o
     * servidor voltou atrás (restore de backup), quem manda é ele — senão o
     * cliente ficaria vendo lacuna em todo evento novo, para sempre. */
    const { invalidateSpy, hook } = setup();
    const socket = FakeWebSocket.instances[0];

    act(() => {
      socket.emit({ type: 'hello', seq: 10, workspace_id: 5 });
      socket.emit({ type: 'transaction.created', seq: 11, workspace_id: 5 });
      vi.advanceTimersByTime(300);
      socket.onclose?.({ code: 1006 });
      vi.advanceTimersByTime(2000);
    });

    const socket2 = FakeWebSocket.instances[1];
    act(() => {
      socket2.emit({ type: 'hello', seq: 5, workspace_id: 5 }); // servidor regrediu
      vi.advanceTimersByTime(300);
    });
    invalidateSpy.mockClear();

    act(() => {
      socket2.emit({ type: 'transaction.created', seq: 6, workspace_id: 5 });
      vi.advanceTimersByTime(300);
    });

    // 6 = 5+1: em ordem. Com o marco preso em 11, isto viraria lacuna e resync.
    expect(invalidateSpy).toHaveBeenCalled();
    expect(invalidateSpy.mock.calls.every((c) => c[0] !== undefined)).toBe(true);
    hook.unmount();
  });

  it('lacuna na sequência dispara resync completo', () => {
    const { invalidateSpy, hook } = setup();
    const socket = FakeWebSocket.instances[0];

    act(() => {
      socket.emit({ type: 'hello', seq: 3, workspace_id: 5 });
      vi.advanceTimersByTime(300);
    });
    invalidateSpy.mockClear();

    act(() => {
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
      vi.advanceTimersByTime(300);
      // Conexão cai (código genérico) → reconecta com backoff
      socket.onclose?.({ code: 1006 });
      vi.advanceTimersByTime(2000);
    });
    // Ignora o resync do PRIMEIRO hello: aqui o que importa é o da divergência
    invalidateSpy.mockClear();

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
