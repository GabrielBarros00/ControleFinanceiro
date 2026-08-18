import { test, expect } from '@playwright/test';

/*
 * O app instalável — a parte que dá para medir contra o servidor de dev.
 *
 * Existe porque nada disso quebra de forma visível. Um manifesto com um campo a
 * menos, um ícone que sumiu de `public/`, a tag `rel="manifest"` removida numa
 * limpeza do `index.html`: o app continua abrindo normalmente, e a única
 * consequência é o Chrome parar de oferecer "Instalar aplicativo" — em produção,
 * sem erro em log nenhum. É o tipo de regressão que só se descobre quando
 * alguém tenta instalar, meses depois.
 *
 * **O service worker NÃO é testado aqui**, e não por esquecimento: ele só é
 * registrado sob `import.meta.env.PROD` (ver `src/main.tsx`) — em dev um SW
 * cacheando os módulos do Vite faria a página parar de refletir o editor. O
 * registro, a ativação, a guarda de `/api/` e a casca offline são medidos em
 * `e2e-prod/pwa.spec.ts`, contra o nginx servindo o `dist` de verdade, que é o
 * único lugar onde o comportamento existe.
 */

test.describe('PWA — manifesto e metas', () => {
  test('o manifesto é servido e tem o que a instalação exige', async ({ request, baseURL }) => {
    const resposta = await request.get(`${baseURL}/manifest.webmanifest`);
    expect(resposta.ok(), 'manifest.webmanifest não foi servido').toBeTruthy();

    const manifesto = JSON.parse(await resposta.text());
    expect(manifesto.name).toBeTruthy();
    expect(manifesto.short_name).toBeTruthy();
    expect(manifesto.start_url).toBeTruthy();
    // `standalone` é o que tira a barra de endereço — sem ele o atalho abre uma
    // aba comum e a pessoa não percebe diferença nenhuma de ter "instalado".
    expect(manifesto.display).toBe('standalone');

    const tamanhos = manifesto.icons.map((i: { sizes: string }) => i.sizes);
    expect(tamanhos, 'o Chrome exige 192 e 512 para oferecer a instalação').toEqual(
      expect.arrayContaining(['192x192', '512x512']),
    );
    // Sem `maskable`, o launcher do Android recorta a arte pelas bordas.
    expect(
      manifesto.icons.some((i: { purpose?: string }) => (i.purpose ?? '').includes('maskable')),
      'falta o ícone maskable',
    ).toBeTruthy();

    // Cada ícone declarado tem de existir: um `src` errado no manifesto é
    // aceito em silêncio e o navegador cai no favicon.
    for (const icone of manifesto.icons as { src: string }[]) {
      const r = await request.get(`${baseURL}${icone.src}`);
      expect(r.ok(), `ícone ausente: ${icone.src}`).toBeTruthy();
    }
  });

  test('o index.html aponta para o manifesto e traz as metas do iOS', async ({ request, baseURL }) => {
    const html = await (await request.get(`${baseURL}/`)).text();
    expect(html).toContain('rel="manifest"');
    // O iOS ignora o manifesto para isto: sem as metas próprias, o atalho abre
    // dentro do Safari, com barra de endereço, e não parece um app.
    expect(html).toContain('apple-mobile-web-app-capable');
    expect(html).toContain('apple-touch-icon-180.png');
    // `viewport-fit=cover` é o que faz `env(safe-area-inset-*)` reportar algo
    // diferente de zero — sem ele a barra inferior fica sob o indicador de home
    // do iPhone, e todo o trabalho de safe-area vira classe morta.
    expect(html).toContain('viewport-fit=cover');
  });

  test('o service worker é servido e mantém a guarda de /api/', async ({ request, baseURL }) => {
    const resposta = await request.get(`${baseURL}/sw.js`);
    expect(resposta.ok(), 'sw.js não foi servido').toBeTruthy();
    const codigo = await resposta.text();
    // Sem handler de `fetch` o Chrome não considera o site instalável.
    expect(codigo).toContain("addEventListener('fetch'");
    // A regra do arquivo, não uma preferência: resposta da API em cache é saldo
    // velho com cara de atual, num app de dinheiro.
    expect(codigo).toContain("startsWith('/api/')");
  });
});
