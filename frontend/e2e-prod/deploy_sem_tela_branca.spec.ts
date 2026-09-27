import { test, expect, type APIRequestContext } from '@playwright/test';

/*
 * Deploy sem tela branca (auditoria 2026-09-26, C6), medido no stack de produção:
 * nginx servindo o `dist`, que é onde moram os três pedaços do defeito.
 *
 * 1. O nginx devolvia o `index.html`, com 200, para QUALQUER caminho — inclusive
 *    `/assets/Chunk-hashantigo.js`. O navegador recebia HTML no lugar do JS.
 * 2. O service worker guardava essa resposta (ela era "ok") e a servia dali em
 *    diante, cache-first.
 * 3. Não havia error boundary: a falha do `import()` desmontava o app inteiro.
 *
 * Quem sofria: toda aba aberta durante um deploy, ao abrir uma tela que ainda não
 * tinha visitado. No app instalado, sem barra do navegador, nem o "recarregar"
 * ficava à vista.
 */

async function umAssetDeVerdade(request: APIRequestContext, baseURL: string): Promise<string> {
  const index = await (await request.get(`${baseURL}/`)).text();
  const achado = /\/assets\/[^"']+\.js/.exec(index);
  expect(achado, 'o index.html não referencia nenhum JS em /assets/').not.toBeNull();
  return achado![0];
}

test.describe('Deploy sem tela branca', () => {
  test('asset que não existe responde 404, e não o index.html', async ({ request, baseURL }) => {
    const r = await request.get(`${baseURL}/assets/ChunkQueSumiu-deadbeef.js`);
    expect(r.status(), 'o fallback da SPA respondeu por um chunk que não existe').toBe(404);
    expect(await r.text()).not.toContain('<div id="root">');
  });

  test('asset com hash é imutável, e continua com os headers de segurança', async ({ request, baseURL }) => {
    const caminho = await umAssetDeVerdade(request, baseURL!);
    const r = await request.get(`${baseURL}${caminho}`);
    expect(r.ok()).toBeTruthy();
    const h = r.headers();
    expect(h['cache-control']).toContain('max-age=31536000');
    expect(h['cache-control']).toContain('immutable');
    // `add_header` num `location` apaga os herdados: o mesmo cuidado do sw.js.
    expect(h['x-content-type-options']).toBe('nosniff');
    expect(h['content-security-policy']).toContain("default-src 'self'");
  });

  test('o index.html é sempre revalidado, venha pelo caminho que vier', async ({ request, baseURL }) => {
    // É ele que aponta para os chunks com hash: um index velho em cache pede os
    // chunks do deploy anterior, que já não existem.
    for (const caminho of ['/', '/index.html', '/overview', '/w/1/settings']) {
      const r = await request.get(`${baseURL}${caminho}`);
      expect(r.ok(), `${caminho} não foi servido`).toBeTruthy();
      expect(r.headers()['cache-control'], `${caminho} sem no-cache`).toContain('no-cache');
      expect(r.headers()['x-frame-options'], `${caminho} perdeu os headers de segurança`).toBe('DENY');
    }
  });

  for (const variante of ['rede recusa o chunk', 'HTML no lugar do JS'] as const) {
    test(`aba de antes do deploy (${variante}): recarrega uma vez e mostra a tela com botão`, async ({ browser, baseURL }) => {
      // `block`: com o SW no meio, o `route` do Playwright não enxergaria o
      // pedido do chunk. O que se mede aqui é a página; o SW tem teste próprio
      // (`src/lib/__tests__/service-worker.test.ts`).
      const context = await browser.newContext({ serviceWorkers: 'block' });
      const page = await context.newPage();
      const index = await (await context.request.get(`${baseURL}/`)).text();

      // O chunk da tela de login é carregado sob demanda (`React.lazy`): some,
      // como sumiria depois de um deploy.
      await page.route(/\/assets\/LoginPage-[^/]+\.js$/, (rota) =>
        variante === 'rede recusa o chunk'
          ? rota.abort()
          : rota.fulfill({ status: 200, contentType: 'text/html', body: index }),
      );

      let carregamentos = 0;
      page.on('load', () => { carregamentos += 1; });

      await page.goto(`${baseURL}/login`);

      await expect(page.getByRole('heading', { name: 'O app foi atualizado' })).toBeVisible({ timeout: 15_000 });
      await expect(page.getByRole('button', { name: 'Recarregar' })).toBeVisible();

      // Uma recarga automática, e só uma: o chunk continua faltando depois dela,
      // e recarregar de novo seria o laço.
      await page.waitForTimeout(3_000);
      expect(carregamentos).toBe(2);

      await context.close();
    });
  }
});
