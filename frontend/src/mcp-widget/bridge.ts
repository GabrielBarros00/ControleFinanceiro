/**
 * A ponte do componente com o host (MCP Apps), escrita à mão.
 *
 * Por que não o `App` oficial (`@modelcontextprotocol/ext-apps`): ele traz o zod e
 * os schemas do protocolo MCP inteiro, ~227 KB dos 263 KB do componente. O
 * componente é baixado e executado de novo em cada resposta que o desenha, então o
 * peso vira memória e tempo de carga na conversa (ADR 0035, seção 8).
 *
 * A conformidade não é presumida: `__tests__/bridge.conformidade.test.ts` põe o
 * host OFICIAL (`AppBridge`, da mesma biblioteca, que valida cada mensagem com os
 * schemas dela) para conversar com esta ponte.
 *
 * O que o componente fala:
 *   → `ui/initialize` (requisição), `ui/notifications/initialized`,
 *     `ui/notifications/size-changed`, `tools/call`, `ui/open-link`,
 *     `ui/request-display-mode` (tela cheia), `ui/update-model-context` (o que a
 *     pessoa fez no componente, para o modelo saber), `ui/message` (pedir algo ao
 *     assistente a partir de um botão)
 *   ← `ui/notifications/tool-result`, `ui/notifications/tool-input` (a entrada da
 *     tool, antes do resultado: a prévia de "registrando…"),
 *     `ui/notifications/host-context-changed`, `ping` e `ui/resource-teardown`
 *     (respondidas), o resto recusado com -32601.
 *
 * Tudo que é opcional no host é usado por DETECÇÃO: o `hostCapabilities` do
 * `ui/initialize` diz se há `updateModelContext` e `message`, e o contexto diz
 * quais modos de exibição existem. No ChatGPT, `window.openai` complementa.
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
export type ModoDeExibicao = 'inline' | 'fullscreen' | 'pip';

/** O que o componente precisa saber do lugar onde está. */
export interface Ambiente {
  modo: ModoDeExibicao;
  modos: ModoDeExibicao[];
  alturaMaxima?: number;
  plataforma?: string;
}

interface OpenAiGlobals {
  toolOutput?: Record<string, unknown> | null;
  toolInput?: Record<string, unknown> | null;
  toolResponseMetadata?: Record<string, unknown> | null;
  theme?: Tema;
  displayMode?: ModoDeExibicao;
  maxHeight?: number;
  callTool?: (name: string, args: Record<string, unknown>) => Promise<ToolResultLike>;
  openExternal?: (args: { href: string }) => void;
  requestDisplayMode?: (args: { mode: ModoDeExibicao }) => Promise<{ mode: ModoDeExibicao }>;
  sendFollowUpMessage?: (args: { prompt: string }) => Promise<void>;
}

declare global {
  interface Window {
    openai?: OpenAiGlobals;
  }
}

export interface Bridge {
  onResult(cb: (r: ToolResultLike) => void): void;
  onTheme(cb: (tema: Tema) => void): void;
  /** A entrada da tool que está rodando (antes do resultado). */
  onToolInput?(cb: (args: Record<string, unknown>) => void): void;
  onAmbiente?(cb: (a: Ambiente) => void): void;
  callTool(name: string, args: Record<string, unknown>): Promise<ToolResultLike>;
  openLink(url: string): void;
  /** Pede outro modo de exibição; devolve o que o host de fato aplicou (ou null). */
  requestDisplayMode?(mode: ModoDeExibicao): Promise<ModoDeExibicao | null>;
  /** Conta ao modelo o que a pessoa fez no componente (sem disparar resposta). */
  updateModelContext?(texto: string): Promise<void>;
  /** Manda uma mensagem ao assistente em nome da pessoa. */
  sendMessage?(texto: string): Promise<boolean>;
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
  displayMode?: ModoDeExibicao;
  availableDisplayModes?: ModoDeExibicao[];
  containerDimensions?: { maxHeight?: number; height?: number };
  platform?: string;
}

interface CapacidadesDoHost {
  updateModelContext?: unknown;
  message?: unknown;
  serverTools?: unknown;
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
  const entradas: Array<(a: Record<string, unknown>) => void> = [];
  const ambientes: Array<(a: Ambiente) => void> = [];
  const pendentes = new Map<number, { ok: (v: unknown) => void; falha: (e: Error) => void }>();
  let proximoId = 1;
  let conectado = false;
  let contexto: ContextoDoHost = {};
  let capacidades: CapacidadesDoHost = {};

  // O último resultado fica guardado para quem se registrar DEPOIS dele. O host
  // manda o resultado logo após o `initialized`, e isso pode chegar antes de o
  // componente registrar o ouvinte (o efeito roda depois da primeira pintura):
  // sem a guarda, o resultado se perdia e a tela ficava no esqueleto para sempre.
  let ultimo: ToolResultLike | null = null;
  let ultimaEntrada: Record<string, unknown> | null = null;
  const entrega = (r: ToolResultLike) => {
    ultimo = r;
    ouvintes.forEach((cb) => cb(r));
  };
  const avisaTema = (tema: unknown) => {
    if (tema === 'dark' || tema === 'light') temas.forEach((cb) => cb(tema));
  };
  const legado = () => (typeof window !== 'undefined' ? window.openai : undefined);
  const ambienteAtual = (): Ambiente => {
    const oa = legado();
    const modo = contexto.displayMode ?? oa?.displayMode ?? 'inline';
    const modos = contexto.availableDisplayModes ?? (oa?.requestDisplayMode ? ['inline', 'fullscreen', 'pip'] : ['inline']);
    const alturaMaxima = contexto.containerDimensions?.maxHeight ?? oa?.maxHeight;
    return { modo, modos, alturaMaxima, plataforma: contexto.platform };
  };
  const avisaAmbiente = () => {
    const a = ambienteAtual();
    ambientes.forEach((cb) => cb(a));
  };
  const aplicaContexto = (novo: ContextoDoHost) => {
    contexto = { ...contexto, ...novo };
    aplicaEstilos(novo.styles?.variables);
    if (novo.theme) avisaTema(novo.theme);
    avisaAmbiente();
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
      else if (m.method === 'ui/notifications/tool-input') {
        const args = ((m.params as { arguments?: Record<string, unknown> })?.arguments) ?? {};
        ultimaEntrada = args;
        entradas.forEach((cb) => cb(args));
      }
    });

    requisita(
      'ui/initialize',
      {
        protocolVersion: VERSAO_DO_PROTOCOLO,
        appInfo: { name: 'controle-financeiro-widget', version: '4.0.0' },
        appCapabilities: { availableDisplayModes: ['inline', 'fullscreen'] },
      },
      TEMPO_DO_HANDSHAKE_MS,
    )
      .then((resposta) => {
        conectado = true;
        const r = (resposta ?? {}) as { hostContext?: ContextoDoHost; hostCapabilities?: CapacidadesDoHost };
        capacidades = r.hostCapabilities ?? {};
        aplicaContexto(r.hostContext ?? {});
        notifica('ui/notifications/initialized');
        observaTamanho((tamanho) => notifica('ui/notifications/size-changed', tamanho));
      })
      .catch(() => {
        // Host sem MCP Apps (ou só com `window.openai`): segue com o que houver.
      });
  }

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
      avisaAmbiente();
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
    onToolInput(cb) {
      entradas.push(cb);
      const inicial = ultimaEntrada ?? legado()?.toolInput ?? null;
      if (inicial) cb(inicial);
    },
    onAmbiente(cb) {
      ambientes.push(cb);
      cb(ambienteAtual());
    },
    async callTool(name, args) {
      if (conectado) {
        return (await requisita('tools/call', { name, arguments: args }, TEMPO_DA_ACAO_MS)) as ToolResultLike;
      }
      const oa = legado();
      if (oa?.callTool) return oa.callTool(name, args);
      throw new Error('Este app de chat não permite ações pelo componente. Peça ao assistente.');
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
    async requestDisplayMode(mode) {
      try {
        if (conectado) {
          const r = (await requisita('ui/request-display-mode', { mode }, TEMPO_DA_ACAO_MS)) as { mode?: ModoDeExibicao };
          const aplicado = r?.mode ?? null;
          if (aplicado) aplicaContexto({ displayMode: aplicado });
          return aplicado;
        }
        const oa = legado();
        if (oa?.requestDisplayMode) {
          const r = await oa.requestDisplayMode({ mode });
          return r?.mode ?? mode;
        }
      } catch {
        // Host que não troca de modo: o componente segue inline.
      }
      return null;
    },
    async updateModelContext(texto) {
      if (!conectado || !capacidades.updateModelContext) return;
      try {
        await requisita('ui/update-model-context', { content: [{ type: 'text', text: texto }] }, TEMPO_DA_ACAO_MS);
      } catch {
        // Contexto é cortesia: a ação já foi feita e a pessoa já viu o resultado.
      }
    },
    async sendMessage(texto) {
      try {
        if (conectado && capacidades.message) {
          const r = (await requisita('ui/message', { role: 'user', content: [{ type: 'text', text: texto }] }, TEMPO_DA_ACAO_MS)) as { isError?: boolean };
          return !r?.isError;
        }
        const oa = legado();
        if (oa?.sendFollowUpMessage) {
          await oa.sendFollowUpMessage({ prompt: texto });
          return true;
        }
      } catch {
        // Sem canal de mensagem: o botão avisa a pessoa.
      }
      return false;
    },
  };
}
