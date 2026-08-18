import { test, expect, type Page } from '@playwright/test';

/*
 * O service worker, medido onde ele existe.
 *
 * O registro é guardado por `import.meta.env.PROD` (`src/main.tsx`): no servidor
 * de desenvolvimento não há SW nenhum, de propósito — um worker cacheando os
 * módulos do Vite faz a página parar de refletir o editor. Então a única forma
 * honesta de testar isto é contra o stack de produção: nginx servindo o `dist`,
 * que é o mesmo binário que vai para o ar.
 *
 * E é aqui, também, que dá para conferir a configuração do nginx — o
 * `Cache-Control: no-cache` do `sw.js`, que existe só neste caminho. Um `sw.js`
 * cacheado por horas prende o aparelho da pessoa numa versão antiga do worker, e
 * é o worker que decide o que mais fica em cache: a falha mais difícil de
 * alcançar depois, porque o conserto mora justamente no arquivo que não é
 * rebuscado.
 */

/** Espera o SW registrado chegar a `activated`. */
async function esperarServiceWorkerAtivo(page: Page) {
  await page.waitForFunction(
    async () => {
      if (!('serviceWorker' in navigator)) return false;
      const reg = await navigator.serviceWorker.getRegistration();
      return reg?.active?.state === 'activated';
    },
    undefined,
    { timeout: 30_000 },
  );
}

test.describe('PWA no stack de produção', () => {
  test('o nginx manda revalidar o sw.js e o manifesto', async ({ request, baseURL }) => {
    for (const caminho of ['/sw.js', '/manifest.webmanifest']) {
      const r = await request.get(`${baseURL}${caminho}`);
      expect(r.ok(), `${caminho} não foi servido`).toBeTruthy();
      expect(
        r.headers()['cache-control'],
        `${caminho} sem no-cache: o aparelho fica preso numa versão antiga`,
      ).toContain('no-cache');
    }
  });

  test('os headers de segurança sobrevivem ao Cache-Control', async ({ request, baseURL }) => {
    /*
     * A armadilha que motivou o `map`: no nginx, um `add_header` dentro de um
     * `location` DESCARTA todos os herdados do nível acima. Escrever
     * `location = /sw.js { add_header Cache-Control ... }` teria apagado os cinco
     * headers de segurança — nosniff, X-Frame-Options, Referrer-Policy,
     * Permissions-Policy e a CSP — exatamente para o arquivo que controla todas
     * as requisições do app. O teste existe para essa regressão não voltar em
     * silêncio na próxima mexida no nginx.conf.
     */
    const r = await request.get(`${baseURL}/sw.js`);
    const headers = r.headers();
    expect(headers['x-content-type-options']).toBe('nosniff');
    expect(headers['x-frame-options']).toBe('DENY');
    expect(headers['referrer-policy']).toBe('same-origin');
    expect(headers['content-security-policy']).toContain("default-src 'self'");
  });

  test('o worker registra, ativa e não deixa a API entrar no cache', async ({ browser, baseURL }) => {
    const context = await browser.newContext({ serviceWorkers: 'allow' });
    const page = await context.newPage();
    await page.goto(`${baseURL}/login`);
    await esperarServiceWorkerAtivo(page);

    /*
     * A regra que não se quebra: `/api/` NUNCA sai do cache.
     *
     * Este é um app de dinheiro, e um saldo cacheado é pior do que saldo
     * nenhum — aparece com cara de atual e ninguém desconfia.
     *
     * O que este teste pega, medido no stack de verdade: trocando o handler por
     * um "cache-first para todo GET" — uma linha, e a forma mais natural de
     * escrever —, três URLs de `/api/` aparecem no Cache Storage e a asserção
     * falha. O que ele NÃO pega é a remoção da linha de guarda em `sw.js`
     * sozinha: hoje ela é redundante (uma requisição de API já cairia no fim do
     * handler sem ser tocada), e por isso quem a protege é o portão do
     * `scripts/verify-build-assets.mjs`, não este teste.
     */
    await page.evaluate(async () => {
      await fetch('/api/v1/health');
      await fetch('/api/v1/health');
    });
    const emCache = await page.evaluate(async () => {
      const nomes = await caches.keys();
      const urls: string[] = [];
      for (const nome of nomes) {
        const cache = await caches.open(nome);
        urls.push(...(await cache.keys()).map((r) => r.url));
      }
      return urls;
    });
    expect(
      emCache.filter((u) => u.includes('/api/')),
      'resposta da API foi para o cache — número velho com cara de atual',
    ).toEqual([]);
    // E a casca precisa ter entrado, senão o teste offline abaixo passaria por
    // acidente (com o HTTP cache do navegador, não com o worker).
    expect(emCache.some((u) => u.endsWith('/index.html') || u.endsWith('/'))).toBeTruthy();

    await context.close();
  });

  test('sem rede, o app mostra a casca em vez do erro do navegador', async ({ browser, baseURL }) => {
    const context = await browser.newContext({ serviceWorkers: 'allow' });
    const page = await context.newPage();

    // Primeira visita COM rede: é ela que popula a casca.
    await page.goto(`${baseURL}/login`);
    await esperarServiceWorkerAtivo(page);
    await page.waitForTimeout(1_000);

    await context.setOffline(true);
    const resposta = await page.goto(`${baseURL}/overview`).catch(() => null);
    expect(resposta, 'a navegação offline não devolveu nada — o fallback não pegou').not.toBeNull();

    // O `<div id="root">` do index.html basta: prova que veio a casca da SPA e
    // não a tela de erro de rede do Chrome. Os DADOS não vêm (a API não é
    // cacheada, e é assim que tem de ser); o que se mede aqui é a casca.
    expect(await page.locator('#root').count()).toBe(1);

    await context.setOffline(false);
    await context.close();
  });
});
