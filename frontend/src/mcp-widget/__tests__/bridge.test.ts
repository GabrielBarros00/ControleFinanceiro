import { afterEach, describe, expect, it, vi } from 'vitest';

/**
 * A ponte com o host, pelo lado do ChatGPT (`window.openai`).
 *
 * O `toolOutput` pode chegar DEPOIS do carregamento, avisado pelo evento
 * `openai:set_globals`. Lido uma vez só no início, o componente ficava em
 * "Carregando…" para sempre. O mesmo evento dispara em toda mudança de global,
 * então o resultado só é reentregue quando é outro.
 *
 * O `App` do MCP Apps é trocado por um que nunca conecta: aqui só interessa o
 * caminho do `window.openai`.
 */
vi.mock('@modelcontextprotocol/ext-apps', () => ({
  App: class {
    ontoolresult: unknown = null;
    onhostcontextchanged: unknown = null;
    connect() {
      return new Promise(() => {});
    }
    getHostContext() {
      return undefined;
    }
  },
}));

const avisar = () => window.dispatchEvent(new Event('openai:set_globals'));

describe('ponte com window.openai', () => {
  afterEach(() => {
    delete window.openai;
  });

  it('entrega o resultado que chega depois do carregamento', async () => {
    window.openai = { toolOutput: null, theme: 'light' };
    const { createBridge } = await import('../bridge');
    const ponte = createBridge();
    const recebidos: unknown[] = [];
    ponte.onResult((r) => recebidos.push(r.structuredContent));
    expect(recebidos).toEqual([]);

    const fatura = { month: '2026-10', total: '10.00' };
    window.openai.toolOutput = fatura;
    avisar();
    expect(recebidos).toEqual([fatura]);

    // Outra global mudou (altura, tema): o mesmo resultado não é reentregue.
    avisar();
    avisar();
    expect(recebidos).toEqual([fatura]);

    const outra = { month: '2026-11', total: '20.00' };
    window.openai.toolOutput = outra;
    avisar();
    expect(recebidos).toEqual([fatura, outra]);
  });

  it('o resultado já presente no carregamento não é entregue de novo pelo evento', async () => {
    const fatura = { month: '2026-10', total: '10.00' };
    window.openai = { toolOutput: fatura };
    const { createBridge } = await import('../bridge');
    const ponte = createBridge();
    const recebidos: unknown[] = [];
    ponte.onResult((r) => recebidos.push(r.structuredContent));
    avisar();
    expect(recebidos).toEqual([fatura]);
  });

  it('segue o tema que muda depois', async () => {
    window.openai = { toolOutput: null, theme: 'light' };
    const { createBridge } = await import('../bridge');
    const ponte = createBridge();
    const temas: string[] = [];
    ponte.onTheme((t) => temas.push(t));
    window.openai.theme = 'dark';
    avisar();
    expect(temas.at(-1)).toBe('dark');
  });
});
