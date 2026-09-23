import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AppBridge } from '@modelcontextprotocol/ext-apps/app-bridge';
import { createBridge, type Mensagem, type Porta, type ToolResultLike } from '../bridge';

/**
 * A ponte escrita à mão contra o HOST OFICIAL do MCP Apps.
 *
 * A ponte oficial (`App`, de `@modelcontextprotocol/ext-apps`) saiu do componente
 * pelo peso (~227 KB). O `AppBridge` é a implementação oficial do OUTRO lado: é o
 * que um host usa, e ele valida cada mensagem que recebe com os schemas do
 * protocolo. Se a nossa ponte mandar algo fora do contrato, é ele que recusa.
 *
 * O transporte é um par em memória. `structuredClone` imita o `postMessage`: só
 * passa o que sobrevive à serialização.
 */
function transporteEmMemoria() {
  let paraOComponente: ((m: Mensagem) => void) | null = null;
  const doHost = {
    onmessage: undefined as ((m: unknown) => void) | undefined,
    onclose: undefined as (() => void) | undefined,
    onerror: undefined as ((e: Error) => void) | undefined,
    async start() {},
    async send(m: unknown) {
      queueMicrotask(() => paraOComponente?.(structuredClone(m) as Mensagem));
    },
    async close() {},
  };
  const porta: Porta = {
    enviar: (m) => queueMicrotask(() => doHost.onmessage?.(structuredClone(m))),
    ouvir: (cb) => {
      paraOComponente = cb;
    },
  };
  return { doHost, porta };
}

async function hostConectado(opcoes: { variaveis?: Record<string, string> } = {}) {
  const { doHost, porta } = transporteEmMemoria();
  const host = new AppBridge(
    null,
    { name: 'host-de-teste', version: '1.0.0' },
    { openLinks: {}, serverTools: {} },
    // O tipo do host exige o mapa COMPLETO de variáveis; o teste manda só as que confere.
    { hostContext: { theme: 'dark', styles: { variables: (opcoes.variaveis ?? {}) as never } } },
  );
  const eventos = { iniciado: false, tamanhos: [] as Array<{ width?: number; height?: number }>, links: [] as string[] };
  host.oninitialized = () => {
    eventos.iniciado = true;
  };
  host.onsizechange = (p) => eventos.tamanhos.push(p);
  host.onopenlink = async ({ url }) => {
    eventos.links.push(url);
    return {};
  };
  host.oncalltool = async ({ name, arguments: args }) => ({
    content: [{ type: 'text', text: `ok ${name}` }],
    structuredContent: { recebido: args ?? null },
  });
  await host.connect(doHost as never);
  const ponte = createBridge(porta);
  await vi.waitFor(() => expect(eventos.iniciado).toBe(true));
  return { host, ponte, eventos };
}

describe('ponte do componente × host oficial do MCP Apps', () => {
  beforeEach(() => {
    // jsdom não tem ResizeObserver: um que só registra basta para o aviso inicial de tamanho.
    vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    document.documentElement.removeAttribute('style');
  });

  it('completa o handshake e o host reconhece o componente', async () => {
    const { host } = await hostConectado();
    expect(host.getAppVersion()).toEqual({ name: 'controle-financeiro-widget', version: '2.0.0' });
    expect(host.getAppCapabilities()).toEqual({ availableDisplayModes: ['inline'] });
  });

  it('avisa o tamanho, e o host aceita o formato', async () => {
    const { eventos } = await hostConectado();
    await vi.waitFor(() => expect(eventos.tamanhos.length).toBeGreaterThan(0));
    expect(eventos.tamanhos[0]).toEqual({ width: expect.any(Number), height: expect.any(Number) });
  });

  it('recebe o resultado da tool', async () => {
    const { host, ponte } = await hostConectado();
    const recebidos: ToolResultLike[] = [];
    ponte.onResult((r) => recebidos.push(r));
    await host.sendToolResult({ content: [], structuredContent: { month: '2026-10', total: '10.00' } });
    await vi.waitFor(() => expect(recebidos).toHaveLength(1));
    expect(recebidos[0].structuredContent).toEqual({ month: '2026-10', total: '10.00' });
  });

  it('o resultado que chega ANTES de o componente se registrar não se perde', async () => {
    // Corrida real: o host manda o resultado logo depois do `initialized`, e o
    // componente só registra o ouvinte no efeito, depois da primeira pintura.
    const { host, ponte } = await hostConectado();
    await host.sendToolResult({ content: [], structuredContent: { month: '2026-10' } });
    await new Promise((r) => setTimeout(r, 0));
    const recebidos: ToolResultLike[] = [];
    ponte.onResult((r) => recebidos.push(r));
    expect(recebidos.map((r) => r.structuredContent)).toEqual([{ month: '2026-10' }]);
  });

  it('segue o tema e as variáveis de estilo do host, no início e quando mudam', async () => {
    const { host, ponte } = await hostConectado({ variaveis: { '--color-background-primary': '#123456' } });
    const temas: string[] = [];
    ponte.onTheme((t) => temas.push(t));
    expect(temas).toEqual(['dark']);
    expect(document.documentElement.style.getPropertyValue('--color-background-primary')).toBe('#123456');
    await host.sendHostContextChange({ theme: 'light', styles: { variables: { '--color-text-primary': '#010203' } as never } });
    await vi.waitFor(() => expect(temas.at(-1)).toBe('light'));
    expect(document.documentElement.style.getPropertyValue('--color-text-primary')).toBe('#010203');
  });

  it('chama a tool pelo host e devolve o resultado', async () => {
    const { ponte } = await hostConectado();
    const r = await ponte.callTool('transactions_bulk_delete', { confirmation_token: 'abc' });
    expect(r.structuredContent).toEqual({ recebido: { confirmation_token: 'abc' } });
  });

  it('pede ao host para abrir o link', async () => {
    const { ponte, eventos } = await hostConectado();
    ponte.openLink('https://app.example/me/cards');
    await vi.waitFor(() => expect(eventos.links).toEqual(['https://app.example/me/cards']));
  });

  it('responde ao desmontar do host', async () => {
    const { host } = await hostConectado();
    await expect(host.teardownResource({})).resolves.toEqual({});
  });
});
