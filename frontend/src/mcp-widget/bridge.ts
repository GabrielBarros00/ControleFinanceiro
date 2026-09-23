/**
 * A ponte do componente com o host, com detecção de capacidade.
 *
 * Padrão primeiro: o `App` do MCP Apps (`@modelcontextprotocol/ext-apps`), que
 * o Claude, o ChatGPT e os demais hosts compatíveis falam por postMessage. Se o
 * host for o ChatGPT com a API antiga (`window.openai`), ela é usada como
 * complemento — lida só se existir, nunca presumida.
 *
 * O componente NUNCA busca dados sozinho (a CSP do recurso é vazia): tudo chega
 * pelo resultado da tool que o host entrega, e ações passam por `callTool`, que
 * o host roteia para o servidor com a MESMA autorização da conversa.
 */
import { App } from '@modelcontextprotocol/ext-apps';

export interface ToolResultLike {
  structuredContent?: Record<string, unknown> | null;
  _meta?: Record<string, unknown> | null;
  isError?: boolean;
  content?: Array<{ type: string; text?: string }>;
}

interface OpenAiGlobals {
  toolOutput?: Record<string, unknown> | null;
  toolResponseMetadata?: Record<string, unknown> | null;
  theme?: 'light' | 'dark';
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
  onTheme(cb: (tema: 'light' | 'dark') => void): void;
  callTool(name: string, args: Record<string, unknown>): Promise<ToolResultLike>;
  openLink(url: string): void;
}

export function createBridge(): Bridge {
  const ouvintes: Array<(r: ToolResultLike) => void> = [];
  const temas: Array<(t: 'light' | 'dark') => void> = [];
  let conectado = false;

  const app = new App({ name: 'controle-financeiro-widget', version: '1.0.0' }, {}, { autoResize: true });
  app.ontoolresult = (params) => {
    ouvintes.forEach((cb) => cb(params as unknown as ToolResultLike));
  };
  app.onhostcontextchanged = (ctx) => {
    if (ctx.theme) temas.forEach((cb) => cb(ctx.theme === 'dark' ? 'dark' : 'light'));
  };
  app
    .connect()
    .then(() => {
      conectado = true;
      const tema = app.getHostContext()?.theme;
      if (tema) temas.forEach((cb) => cb(tema === 'dark' ? 'dark' : 'light'));
    })
    .catch(() => {
      // Host sem MCP Apps (ou só com `window.openai`): segue com o que houver.
    });

  const legado = () => (typeof window !== 'undefined' ? window.openai : undefined);

  return {
    onResult(cb) {
      ouvintes.push(cb);
      const oa = legado();
      if (oa?.toolOutput) cb({ structuredContent: oa.toolOutput, _meta: oa.toolResponseMetadata ?? null });
    },
    onTheme(cb) {
      temas.push(cb);
      const oa = legado();
      if (oa?.theme) cb(oa.theme);
    },
    async callTool(name, args) {
      if (conectado) {
        return (await app.callServerTool({ name, arguments: args })) as unknown as ToolResultLike;
      }
      const oa = legado();
      if (oa?.callTool) return oa.callTool(name, args);
      throw new Error('Este app de chat não permite ações pelo componente. Peça ao assistente para confirmar.');
    },
    openLink(url) {
      if (conectado) {
        void app.openLink({ url }).catch(() => window.open(url, '_blank', 'noopener'));
        return;
      }
      const oa = legado();
      if (oa?.openExternal) oa.openExternal({ href: url });
      else window.open(url, '_blank', 'noopener');
    },
  };
}
