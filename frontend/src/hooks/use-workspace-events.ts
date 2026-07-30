import * as React from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { apiClient, baseURL } from '@/api/client';
import { useAuthStore } from '@/stores';
import { FULL_RESYNC, keysForEvent } from '@/lib/ws-events';
import { useWorkspaceId } from './use-workspace-id';

export { keysForEvent } from '@/lib/ws-events';

const DEBOUNCE_MS = 250;
const STALE_CONNECTION_MS = 45_000; // servidor manda ping a cada 30s
const MAX_BACKOFF_MS = 30_000;

export function wsUrl(workspaceId: number): string {
  const base = baseURL.startsWith('http')
    ? baseURL
    : `${window.location.origin}${baseURL}`;
  return `${base.replace(/^http/, 'ws')}/ws/workspaces/${workspaceId}`;
}

/**
 * Mantém uma conexão WebSocket com o workspace atual e invalida queries do
 * TanStack Query quando outros clientes fazem mutações.
 *
 * Integridade: o servidor numera eventos por workspace (seq). Se o cliente
 * detecta lacuna (seq != last+1) ou reconecta com hello.seq à frente do que
 * viu, faz resync completo (invalida todas as queries).
 */
export function useWorkspaceEvents() {
  const queryClient = useQueryClient();
  const currentWorkspaceId = useWorkspaceId();
  const { isAuthenticated } = useAuthStore();

  // last seq visto por workspace (sobrevive a reconexões na mesma sessão)
  const lastSeqRef = React.useRef<Map<number, number>>(new Map());
  // Workspaces cujo cache JÁ está correlacionado com um seq conhecido.
  // Enquanto um workspace não está aqui, `hello.seq` não diz nada sobre o que
  // temos em cache — ver o resync na primeira conexão, abaixo.
  const syncedRef = React.useRef<Set<number>>(new Set());

  React.useEffect(() => {
    if (!isAuthenticated || !currentWorkspaceId) return;

    const wsId = currentWorkspaceId;
    let socket: WebSocket | null = null;
    let closedByUnmount = false;
    let attempts = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let staleTimer: ReturnType<typeof setInterval> | null = null;
    let debounceTimer: ReturnType<typeof setTimeout> | null = null;
    let lastMessageAt = Date.now();
    const pendingKeys = new Set<string>();
    let fullResyncPending = false;

    const flushInvalidations = () => {
      debounceTimer = null;
      if (fullResyncPending) {
        fullResyncPending = false;
        pendingKeys.clear();
        queryClient.invalidateQueries();
        return;
      }
      for (const keyJson of pendingKeys) {
        queryClient.invalidateQueries({ queryKey: JSON.parse(keyJson) });
      }
      pendingKeys.clear();
    };

    const scheduleFlush = () => {
      if (!debounceTimer) {
        debounceTimer = setTimeout(flushInvalidations, DEBOUNCE_MS);
      }
    };

    const requestFullResync = () => {
      fullResyncPending = true;
      scheduleFlush();
    };

    const connect = () => {
      if (closedByUnmount) return;
      socket = new WebSocket(wsUrl(wsId));
      // Maior seq entregue NESTA conexão (undefined até o primeiro evento).
      // Só ele protege o marco contra o `hello` — ver abaixo.
      let seqNestaConexao: number | undefined;

      socket.onmessage = (raw: MessageEvent) => {
        lastMessageAt = Date.now();
        let msg: { type?: string; seq?: number; resource_type?: string; event_type?: string };
        try {
          msg = JSON.parse(raw.data);
        } catch {
          return;
        }

        if (msg.type === 'ping' || msg.type === 'pong') return;

        if (msg.type === 'hello') {
          attempts = 0;
          const helloSeq = msg.seq as number;
          const lastSeen = lastSeqRef.current.get(wsId);

          if (!syncedRef.current.has(wsId)) {
            // PRIMEIRA conexão com este workspace nesta sessão (carga da página
            // ou troca pelo switcher). O cache foi preenchido por HTTP sem
            // nenhuma correlação com o seq: qualquer mutação commitada entre o
            // GET e a entrada na sala já está contada em `hello.seq` mas NÃO
            // está nos dados — e não gera lacuna depois (o próximo evento vem
            // em ordem), então ficaria invisível para sempre. Era exatamente o
            // sintoma da troca de workspace: socket novo recebia o `hello` e o
            // lançamento do outro membro só aparecia com F5. Resync aqui é o
            // único jeito de correlacionar cache e seq.
            requestFullResync();
            syncedRef.current.add(wsId);
          } else if (lastSeen !== undefined && helloSeq !== lastSeen) {
            // Reconexão: perdemos eventos enquanto desconectados → resync
            requestFullResync();
          }

          // O `hello` é a verdade do servidor, EXCETO se esta mesma conexão já
          // entregou algo à frente: o socket entra na sala antes de o servidor
          // ler o seq, então um evento pode chegar antes do `hello` e voltar o
          // marcador atrás inventaria uma lacuna no evento seguinte. Marco de
          // conexão ANTERIOR não protege nada (se o servidor voltou atrás — um
          // restore de backup, por exemplo, quem manda é ele).
          lastSeqRef.current.set(wsId, Math.max(helloSeq, seqNestaConexao ?? helloSeq));
          return;
        }

        if (typeof msg.seq === 'number') {
          const lastSeen = lastSeqRef.current.get(wsId);
          lastSeqRef.current.set(wsId, msg.seq);
          seqNestaConexao = Math.max(msg.seq, seqNestaConexao ?? msg.seq);
          if (lastSeen !== undefined && msg.seq !== lastSeen + 1) {
            // Lacuna na sequência → resync completo
            requestFullResync();
            return;
          }
          const keys = keysForEvent(msg.type ?? '', wsId);
          if (keys === FULL_RESYNC) {
            // Evento que reescreve toda agregação (ex.: troca de moeda-base)
            requestFullResync();
            return;
          }
          for (const key of keys) {
            pendingKeys.add(JSON.stringify(key));
          }
          scheduleFlush();
        }
      };

      socket.onclose = async (event: CloseEvent) => {
        socket = null;
        if (closedByUnmount) return;

        if (event.code === 4403) return; // sem permissão: não insistir

        if (event.code === 4401) {
          // Token expirou durante a conexão: renova a sessão e reconecta
          try {
            await apiClient.post('/auth/refresh');
            connect();
            return;
          } catch {
            return; // interceptor/store cuidam do logout
          }
        }

        // Backoff exponencial com jitter (1s → 30s)
        attempts += 1;
        const delay = Math.min(1000 * 2 ** (attempts - 1), MAX_BACKOFF_MS);
        const jitter = delay * (0.5 + Math.random() * 0.5);
        reconnectTimer = setTimeout(connect, jitter);
      };

      socket.onerror = () => {
        // onclose cuida da reconexão
      };
    };

    connect();

    // Watchdog: sem mensagens (nem ping) há muito tempo → conexão morta
    staleTimer = setInterval(() => {
      if (socket && Date.now() - lastMessageAt > STALE_CONNECTION_MS) {
        try {
          socket.close();
        } catch {
          /* noop */
        }
      }
    }, STALE_CONNECTION_MS / 3);

    return () => {
      closedByUnmount = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (staleTimer) clearInterval(staleTimer);
      if (debounceTimer) {
        clearTimeout(debounceTimer);
        flushInvalidations();
      }
      if (socket) {
        try {
          socket.close();
        } catch {
          /* noop */
        }
      }
    };
  }, [currentWorkspaceId, isAuthenticated, queryClient]);
}
