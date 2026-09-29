import * as React from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { baseURL, renovacaoRecusada, renovarSessao } from '@/api/client';
import { useAuthStore } from '@/stores';
import { FULL_RESYNC, keysForEvent } from '@/lib/ws-events';
import { seqDoBootstrap } from '@/lib/seq-do-bootstrap';
import { useWorkspaceId } from './use-workspace-id';

export { keysForEvent } from '@/lib/ws-events';

const DEBOUNCE_MS = 250;
const STALE_CONNECTION_MS = 45_000; // servidor manda ping a cada 30s
const MAX_BACKOFF_MS = 30_000;
// Na volta da aba, quanto esperar a resposta ao `ping` antes de dar o socket por
// morto. O vigia de 45 s é para o socket que morre com a aba à vista; na volta
// do aparelho, esperar 45 s é deixar a tela sem tempo real à toa.
const SONDA_MS = 5_000;
const ABERTO = 1; // WebSocket.OPEN

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
    // 4403 (sem acesso) ou sessão recusada: não há o que tentar de novo.
    let desistiu = false;
    let renovando = false;
    let attempts = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let staleTimer: ReturnType<typeof setInterval> | null = null;
    let sondaTimer: ReturnType<typeof setTimeout> | null = null;
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

    /** Backoff exponencial com jitter (1s → 30s). */
    const reconectar = () => {
      if (closedByUnmount || desistiu || reconnectTimer) return;
      attempts += 1;
      const delay = Math.min(1000 * 2 ** (attempts - 1), MAX_BACKOFF_MS);
      const jitter = delay * (0.5 + Math.random() * 0.5);
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, jitter);
    };

    /*
     * Larga o socket SEM esperar o `onclose`.
     *
     * Numa conexão que morreu com o aparelho dormindo, `close()` inicia o aperto
     * de mão de fechamento, e o outro lado nunca responde: o `onclose` só vinha
     * quando o navegador desistisse, e até lá não havia reconexão. Desligando os
     * handlers, o socket velho morre sozinho e o novo pode nascer agora.
     */
    const descartar = () => {
      const morto = socket;
      socket = null;
      if (sondaTimer) {
        clearTimeout(sondaTimer);
        sondaTimer = null;
      }
      if (!morto) return;
      morto.onmessage = null;
      morto.onclose = null;
      morto.onerror = null;
      try {
        morto.close();
      } catch {
        /* noop */
      }
    };

    const connect = () => {
      if (closedByUnmount || desistiu) return;
      socket = new WebSocket(wsUrl(wsId));
      // Prazo novo para o socket novo: sem isto o vigia media o silêncio do
      // socket ANTERIOR e podia derrubar este antes de o `hello` chegar.
      lastMessageAt = Date.now();
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
            // ou troca pelo switcher). O cache foi preenchido por HTTP: uma
            // mutação commitada entre o GET e a entrada na sala já está contada
            // em `hello.seq` mas NÃO nos dados — e não gera lacuna depois (o
            // próximo evento vem em ordem), então ficaria invisível para
            // sempre. Era o sintoma da troca de workspace: socket novo recebia
            // o `hello` e o lançamento do outro membro só aparecia com F5.
            //
            // O seq lido no bootstrap, ANTES de a página buscar qualquer dado,
            // correlaciona as duas coisas: igual ao `hello`, nada mudou no meio
            // e o cache está em dia. Sem ele, ou com qualquer diferença, resync
            // completo — que antes acontecia em TODA carga de página e dobrava
            // as requisições (auditoria 2026-09-26, P2; `lib/seq-do-bootstrap.ts`).
            if (seqDoBootstrap(wsId) !== helloSeq) requestFullResync();
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

      socket.onclose = (event: CloseEvent) => {
        socket = null;
        if (closedByUnmount) return;

        if (event.code === 4403) {
          desistiu = true; // sem permissão: não insistir
          return;
        }

        if (event.code === 4401) {
          /*
           * O token venceu (o servidor confere no aperto de mão): renova e
           * reconecta. A renovação é a MESMA das consultas HTTP: na volta do
           * aparelho as duas corriam juntas, cada uma com o seu `/auth/refresh`,
           * e o servidor lia a segunda como roubo e derrubava a sessão (ADR 0013).
           *
           * Falha de rede na renovação não é desistência — antes era, e o tempo
           * real morria calado até o F5. Recusa (a sessão acabou) é: quem cuida
           * dela é `renovarSessao`, que desloga, e o logout desmonta este efeito.
           */
          renovando = true;
          renovarSessao().then(
            () => {
              renovando = false;
              // Pelo backoff, e não na hora: se o servidor recusar o socket de
              // novo, isto não vira um laço de renovações.
              reconectar();
            },
            (erro: unknown) => {
              renovando = false;
              if (renovacaoRecusada(erro)) desistiu = true;
              else reconectar();
            },
          );
          return;
        }

        reconectar();
      };

      socket.onerror = () => {
        // onclose cuida da reconexão
      };
    };

    /*
     * A aba voltou (ou a rede): o socket pode ter morrido no caminho.
     *
     * Escondida, a aba tem os timers estrangulados pelo navegador; com o aparelho
     * dormindo, a conexão cai sem aviso. Na volta, trata já o que houver:
     *
     * - esperando a próxima tentativa (o backoff pode estar em 30 s): tenta agora;
     * - socket mudo além do prazo do vigia: morto, troca;
     * - socket aparentemente vivo: manda um `ping` e dá `SONDA_MS` para o servidor
     *   responder — uma conexão morta aceita o envio e nunca responde.
     */
    const retomar = () => {
      if (closedByUnmount || desistiu || renovando) return;
      const reconectarJa = () => {
        descartar();
        if (reconnectTimer) {
          clearTimeout(reconnectTimer);
          reconnectTimer = null;
        }
        attempts = 0;
        connect();
      };
      if (!socket || Date.now() - lastMessageAt > STALE_CONNECTION_MS) {
        reconectarJa();
        return;
      }
      const alvo = socket;
      if (alvo.readyState !== ABERTO || sondaTimer) return;
      const enviadoEm = Date.now();
      try {
        alvo.send('ping');
      } catch {
        return;
      }
      sondaTimer = setTimeout(() => {
        sondaTimer = null;
        if (socket === alvo && lastMessageAt < enviadoEm) reconectarJa();
      }, SONDA_MS);
    };

    const aoMudarVisibilidade = () => {
      if (document.visibilityState === 'visible') retomar();
    };
    document.addEventListener('visibilitychange', aoMudarVisibilidade);
    window.addEventListener('online', retomar);

    connect();

    // Watchdog: sem mensagens (nem ping) há muito tempo → conexão morta
    staleTimer = setInterval(() => {
      if (socket && Date.now() - lastMessageAt > STALE_CONNECTION_MS) {
        descartar();
        reconectar();
      }
    }, STALE_CONNECTION_MS / 3);

    return () => {
      closedByUnmount = true;
      document.removeEventListener('visibilitychange', aoMudarVisibilidade);
      window.removeEventListener('online', retomar);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (staleTimer) clearInterval(staleTimer);
      if (sondaTimer) clearTimeout(sondaTimer);
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
