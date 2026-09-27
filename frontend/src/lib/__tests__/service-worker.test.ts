import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { runInNewContext } from 'node:vm';
import { describe, expect, it } from 'vitest';

/*
 * O `public/sw.js` DE VERDADE, executado num sandbox com `self`, `caches` e
 * `fetch` falsos. O SW só existe no build de produção, e o e2e-prod mede o que o
 * nginx devolve; este teste mede a regra do próprio worker, sem depender do
 * servidor: HTML em `/assets/` nunca entra no cache (auditoria 2026-09-26, C6).
 */

const FONTE = readFileSync(join(__dirname, '..', '..', '..', 'public', 'sw.js'), 'utf-8');
const ORIGEM = 'https://app.test';

type Ouvinte = (evento: unknown) => void;

function carregarWorker(respostaDaRede: () => Response) {
  const ouvintes: Record<string, Ouvinte> = {};
  const guardados: { cache: string; url: string; tipo: string | null }[] = [];
  const armazenados = new Map<string, Response>();

  const caches = {
    match: async (req: Request | string) => {
      const url = typeof req === 'string' ? req : req.url;
      return armazenados.get(url)?.clone();
    },
    open: async (nome: string) => ({
      put: async (req: Request | string, resposta: Response) => {
        const url = typeof req === 'string' ? req : req.url;
        guardados.push({ cache: nome, url, tipo: resposta.headers.get('content-type') });
        armazenados.set(url, resposta);
      },
    }),
    keys: async () => [],
    delete: async () => true,
  };

  runInNewContext(FONTE, {
    self: {
      location: { origin: ORIGEM },
      addEventListener: (tipo: string, fn: Ouvinte) => { ouvintes[tipo] = fn; },
      skipWaiting: () => {},
      clients: { claim: async () => {} },
      registration: {},
    },
    caches,
    fetch: async () => respostaDaRede(),
    URL,
    Response,
    console,
  });

  /** Dispara um `fetch` no worker e devolve o que ele respondeu. */
  async function pedir(caminho: string): Promise<Response | undefined> {
    let resposta: Promise<Response> | undefined;
    ouvintes.fetch({
      request: new Request(`${ORIGEM}${caminho}`),
      respondWith: (p: Promise<Response>) => { resposta = p; },
    });
    const r = await resposta;
    // O `cache.put` é disparado sem `await` dentro do worker.
    await new Promise((ok) => setTimeout(ok, 0));
    return r;
  }

  return { pedir, guardados, armazenados };
}

const html = () => new Response('<!doctype html><div id="root"></div>', {
  status: 200, headers: { 'content-type': 'text/html' },
});
const js = () => new Response('export const x = 1;', {
  status: 200, headers: { 'content-type': 'application/javascript' },
});

describe('service worker: cache de /assets/', () => {
  it('o index.html devolvido no lugar de um chunk NÃO entra no cache', async () => {
    const worker = carregarWorker(html);
    const resposta = await worker.pedir('/assets/SettingsPage-deadbeef.js');

    expect(resposta?.status).toBe(200);
    expect(worker.guardados).toEqual([]);
  });

  it('o JS de verdade entra, e é servido do cache na próxima vez', async () => {
    let buscas = 0;
    const worker = carregarWorker(() => { buscas += 1; return js(); });

    await worker.pedir('/assets/SettingsPage-C0oYWdxZ.js');
    await worker.pedir('/assets/SettingsPage-C0oYWdxZ.js');

    expect(worker.guardados).toEqual([
      expect.objectContaining({ url: `${ORIGEM}/assets/SettingsPage-C0oYWdxZ.js`, tipo: 'application/javascript' }),
    ]);
    expect(buscas).toBe(1);
  });

  it('um HTML que já estava no cache é ignorado e rebuscado', async () => {
    let buscas = 0;
    const worker = carregarWorker(() => { buscas += 1; return js(); });
    // O aparelho de quem usou a v2: o HTML envenenado ficou guardado.
    worker.armazenados.set(`${ORIGEM}/assets/SettingsPage-C0oYWdxZ.js`, html());

    const resposta = await worker.pedir('/assets/SettingsPage-C0oYWdxZ.js');

    expect(buscas).toBe(1);
    expect(resposta?.headers.get('content-type')).toBe('application/javascript');
  });

  it('404 não entra no cache', async () => {
    const worker = carregarWorker(() => new Response('', { status: 404 }));
    await worker.pedir('/assets/SettingsPage-deadbeef.js');
    expect(worker.guardados).toEqual([]);
  });

  it('a versão subiu: o cache da v2, que guardava o HTML, é descartado na ativação', () => {
    expect(FONTE).toMatch(/const VERSAO = 'cf4-v3';/);
  });
});
