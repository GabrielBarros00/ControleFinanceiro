/**
 * A ponte do componente com o host (MCP Apps), escrita à mão.
 *
 * Por que não o `App` oficial (`@modelcontextprotocol/ext-apps`): ele traz o zod e
 * os schemas do protocolo MCP inteiro, ~227 KB dos 263 KB do componente. Este
 * componente usa seis mensagens. O componente é baixado e executado de novo em
 * cada resposta que o desenha, então o peso vira memória e tempo de carga na
 * conversa (ADR 0035, seção 8).
 *
 * A conformidade não é presumida: `__tests__/bridge.conformidade.test.ts` põe o
 * host OFICIAL (`AppBridge`, da mesma biblioteca, que valida cada mensagem com os
 * schemas dela) para conversar com esta ponte.
 *
 * O que o componente fala:
 *   → `ui/initialize` (requisição), `ui/notifications/initialized`,
 *     `ui/notifications/size-changed`, `tools/call`, `ui/open-link`
 *   ← `ui/notifications/tool-result`, `ui/notifications/host-context-changed`,
 *     `ping` e `ui/resource-teardown` (respondidas), o resto recusado com -32601.
 *
 * No ChatGPT, `window.openai` complementa: lido só se existir, nunca presumido.
 *
 * O componente NUNCA busca dados sozinho (a CSP do recurso é vazia): tudo chega
 * pelo resultado da tool que o host entrega, e ações passam por `callTool`, que o
 * host roteia para o servidor com a MESMA autorização da conversa.
 */

export interface ToolResultLike {
  structuredContent?: Record<string, unknown> | null;
  _meta?: Record<string, unknown> | null;
  isError?: boolean;
  content?: Array<{ type: string; text?: string }>;
}

export type Tema = 'light' | 'dark';

interface OpenAiGlobals {
  toolOutput?: Record<string, unknown> | null;
  toolResponseMetadata?: Record<string, unknown> | null;
  theme?: Tema;
  callTool?: (name: string, args: Record<string, unknown>) => Promise<ToolResultLike>;
  openExternal?: (args: { href: string }) => void;
}

declare global {
  interface Window {
    openai?: OpenAiGlobals;
  }
}

export interface Bridge {
  onResult(cb: (r: ToolResultLike) => void): void;
  onTheme(cb: (tema: Tema) => void): void;
  callTool(name: string, args: Record<string, unknown>): Promise<ToolResultLike>;
  openLink(url: string): void;
}

/** Mensagem JSON-RPC 2.0, o envelope do MCP Apps. */
export interface Mensagem {
  jsonrpc: '2.0';
  id?: number | string;
  method?: string;
  params?: unknown;
  result?: unknown;
  error?: { code: number; message: string };
}

/** Por onde as mensagens passam: o `window.parent` no host real; um par em memória no teste. */
export interface Porta {
  enviar(m: Mensagem): void;
  ouvir(cb: (m: Mensagem) => void): void;
}

/** A versão que o componente pede; o host responde com a que vai usar. */
export const VERSAO_DO_PROTOCOLO = '2026-01-26';
const TEMPO_DO_HANDSHAKE_MS = 10_000;
const TEMPO_DA_ACAO_MS = 60_000;

interface ContextoDoHost {
  theme?: string;
  styles?: { variables?: Record<string, unknown> };
}

/** A porta do iframe: fala com o `window.parent` e só ouve o que vem DELE (como a ponte oficial). */
export function portaDoHost(): Porta | null {
  if (typeof window === 'undefined' || window.parent === window) return null;
  return {
    enviar: (m) => window.parent.postMessage(m, '*'),
    ouvir: (cb) =>
      window.addEventListener('message', (evento) => {
        const dado = evento.data as Mensagem | undefined;
        if (evento.source === window.parent && dado?.jsonrpc === '2.0') cb(dado);
      }),
  };
}

/**
 * Aplica as variáveis de estilo do host (`--color-background-primary`,
 * `--font-sans`…), o vocabulário do MCP Apps. O CSS do componente lê cada uma com
 * o próprio valor como reserva, então um host que não manda nada continua com o
 * visual padrão. Só propriedades customizadas (`--*`) e valores em texto.
 */
function aplicaEstilos(variaveis: Record<string, unknown> | undefined) {
  if (!variaveis || typeof document === 'undefined') return;
  for (const [nome, valor] of Object.entries(variaveis)) {
    if (nome.startsWith('--') && typeof valor === 'string') document.documentElement.style.setProperty(nome, valor);
  }
}

/**
 * Avisa o host do tamanho do conteúdo. Mesmo algoritmo do `App` oficial: mede o
 * `<html>` com `height: max-content` (o tamanho do CONTEÚDO, não o do iframe, senão
 * o host e o componente se realimentam) e só avisa quando muda.
 */
function observaTamanho(avisa: (tamanho: { width: number; height: number }) => void) {
  if (typeof ResizeObserver === 'undefined') return;
  let agendado = false;
  let largura = 0;
  let altura = 0;
  const mede = () => {
    if (agendado) return;
    agendado = true;
    requestAnimationFrame(() => {
      agendado = false;
      const html = document.documentElement;
      const antes = html.style.height;
      html.style.height = 'max-content';
      const h = Math.ceil(html.getBoundingClientRect().height);
      html.style.height = antes;
      const w = Math.ceil(window.innerWidth);
      if (w !== largura || h !== altura) {
        largura = w;
        altura = h;
        avisa({ width: w, height: h });
      }
    });
  };
  mede();
  const observador = new ResizeObserver(mede);
  observador.observe(document.documentElement);
  observador.observe(document.body);
}

export function createBridge(porta: Porta | null = portaDoHost()): Bridge {
  const ouvintes: Array<(r: ToolResultLike) => void> = [];
  const temas: Array<(t: Tema) => void> = [];
  const pendentes = new Map<number, { ok: (v: unknown) => void; falha: (e: Error) => void }>();
  let proximoId = 1;
  let conectado = false;
  let contexto: ContextoDoHost = {};

  // O último resultado fica guardado para quem se registrar DEPOIS dele. O host
  // manda o resultado logo após o `initialized`, e isso pode chegar antes de o
  // componente registrar o ouvinte (o efeito roda depois da primeira pintura):
  // sem a guarda, o resultado se perdia e a tela ficava no esqueleto para sempre.
  let ultimo: ToolResultLike | null = null;
  const entrega = (r: ToolResultLike) => {
    ultimo = r;
    ouvintes.forEach((cb) => cb(r));
  };
  const avisaTema = (tema: unknown) => {
    if (tema === 'dark' || tema === 'light') temas.forEach((cb) => cb(tema));
  };
  const aplicaContexto = (novo: ContextoDoHost) => {
    contexto = { ...contexto, ...novo };
    aplicaEstilos(novo.styles?.variables);
    if (novo.theme) avisaTema(novo.theme);
  };

  const requisita = (method: string, params: unknown, prazoMs: number): Promise<unknown> =>
    new Promise((ok, falha) => {
      if (!porta) return falha(new Error('Sem host MCP Apps.'));
      const id = proximoId++;
      const prazo = setTimeout(() => {
        pendentes.delete(id);
        falha(new Error(`O app de chat não respondeu a ${method}.`));
      }, prazoMs);
      pendentes.set(id, {
        ok: (v) => { clearTimeout(prazo); ok(v); },
        falha: (e) => { clearTimeout(prazo); falha(e); },
      });
      porta.enviar({ jsonrpc: '2.0', id, method, params });
    });

  const notifica = (method: string, params: unknown = {}) => porta?.enviar({ jsonrpc: '2.0', method, params });

  if (porta) {
    porta.ouvir((m) => {
      // Resposta a uma requisição nossa.
      if (m.id !== undefined && !m.method) {
        const espera = pendentes.get(Number(m.id));
        if (!espera) return;
        pendentes.delete(Number(m.id));
        if (m.error) espera.falha(new Error(m.error.message || 'Erro do app de chat.'));
        else espera.ok(m.result);
        return;
      }
      // Requisição do host: responder sempre, nem que seja "não sei".
      if (m.id !== undefined && m.method) {
        const conhecida = m.method === 'ping' || m.method === 'ui/resource-teardown';
        porta.enviar(
          conhecida
            ? { jsonrpc: '2.0', id: m.id, result: {} }
            : { jsonrpc: '2.0', id: m.id, error: { code: -32601, message: `Método não suportado: ${m.method}` } },
        );
        return;
      }
      // Notificação do host.
      if (m.method === 'ui/notifications/tool-result') entrega(m.params as ToolResultLike);
      else if (m.method === 'ui/notifications/host-context-changed') aplicaContexto(m.params as ContextoDoHost);
    });

    requisita(
      'ui/initialize',
      {
        protocolVersion: VERSAO_DO_PROTOCOLO,
        appInfo: { name: 'controle-financeiro-widget', version: '2.0.0' },
        appCapabilities: { availableDisplayModes: ['inline'] },
      },
      TEMPO_DO_HANDSHAKE_MS,
    )
      .then((resposta) => {
        conectado = true;
        aplicaContexto(((resposta as { hostContext?: ContextoDoHost })?.hostContext) ?? {});
        notifica('ui/notifications/initialized');
        observaTamanho((tamanho) => notifica('ui/notifications/size-changed', tamanho));
      })
      .catch(() => {
        // Host sem MCP Apps (ou só com `window.openai`): segue com o que houver.
      });
  }

  const legado = () => (typeof window !== 'undefined' ? window.openai : undefined);

  // No ChatGPT o `toolOutput` pode chegar DEPOIS do carregamento (é `null` até
  // lá), e o aviso é o evento `openai:set_globals`. Lido uma vez só no início, o
  // componente ficava em "Carregando…" para sempre. O mesmo evento dispara em
  // toda mudança de global (altura, tema…), então só entrega resultado NOVO:
  // reentregar o mesmo objeto re-renderizaria à toa.
  let ultimoLegado: unknown = null;
  if (typeof window !== 'undefined') {
    window.addEventListener('openai:set_globals', () => {
      const oa = legado();
      if (oa?.toolOutput && oa.toolOutput !== ultimoLegado) {
        ultimoLegado = oa.toolOutput;
        entrega({ structuredContent: oa.toolOutput, _meta: oa.toolResponseMetadata ?? null });
      }
      if (oa?.theme) avisaTema(oa.theme);
    });
  }

  return {
    onResult(cb) {
      ouvintes.push(cb);
      if (ultimo) {
        cb(ultimo);
        return;
      }
      const oa = legado();
      if (oa?.toolOutput) {
        ultimoLegado = oa.toolOutput;
        ultimo = { structuredContent: oa.toolOutput, _meta: oa.toolResponseMetadata ?? null };
        cb(ultimo);
      }
    },
    onTheme(cb) {
      temas.push(cb);
      const tema = contexto.theme ?? legado()?.theme;
      if (tema === 'dark' || tema === 'light') cb(tema);
    },
    async callTool(name, args) {
      if (conectado) {
        return (await requisita('tools/call', { name, arguments: args }, TEMPO_DA_ACAO_MS)) as ToolResultLike;
      }
      const oa = legado();
      if (oa?.callTool) return oa.callTool(name, args);
      throw new Error('Este app de chat não permite ações pelo componente. Peça ao assistente para confirmar.');
    },
    openLink(url) {
      const planoB = () => {
        const oa = legado();
        if (oa?.openExternal) oa.openExternal({ href: url });
        else window.open(url, '_blank', 'noopener');
      };
      if (conectado) {
        requisita('ui/open-link', { url }, TEMPO_DA_ACAO_MS)
          .then((r) => { if ((r as { isError?: boolean })?.isError) planoB(); })
          .catch(planoB);
        return;
      }
      planoB();
    },
  };
}
