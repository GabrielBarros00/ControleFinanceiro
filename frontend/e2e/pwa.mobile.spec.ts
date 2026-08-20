import { test, expect, type Browser, type Page } from '@playwright/test';

const API = 'http://localhost:8000/api/v1';

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

    /*
     * A entrada auto-referente em `related_applications` é o que liga o
     * `getInstalledRelatedApps()` — a única forma de o app saber se existe um
     * aplicativo instalado NESTE APARELHO quando se está numa aba comum. Sem
     * ela o Chrome devolve lista vazia sempre, e o diagnóstico de Configurações
     * não conseguiria separar "não instalado" de "instalado, mas você abriu
     * pelo navegador" — que é exatamente a distinção entre um app de verdade
     * (WebAPK) e um mero atalho de tela inicial.
     *
     * O manifesto é JSON e não aceita comentário, então a explicação mora aqui.
     */
    expect(
      (manifesto.related_applications ?? []).some(
        (app: { platform?: string }) => app.platform === 'webapp',
      ),
      'sem a entrada auto-referente em related_applications, getInstalledRelatedApps() sempre volta vazio',
    ).toBeTruthy();

    /*
     * E o campo que, trocado, apaga a instalação inteira em silêncio.
     *
     * `prefer_related_applications: true` diz ao Chrome "prefira o app nativo":
     * ele para de disparar `beforeinstallprompt` e para de oferecer "Instalar".
     * O app continua abrindo normalmente e nada aparece em log nenhum — é a
     * mesma família de regressão invisível que trouxe este arquivo à vida, e
     * fica a UMA palavra de distância de quem mexer em `related_applications`
     * logo acima.
     */
    expect(
      manifesto.prefer_related_applications,
      'prefer_related_applications: true faz o Chrome parar de oferecer a instalação',
    ).toBe(false);

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

/*
 * ---------------------------------------------------------------------------
 * O convite para instalar, na barra superior
 * ---------------------------------------------------------------------------
 *
 * O app era instalável desde sempre — o que não existia era a porta. A oferta
 * morava no fim de Configurações › Aparência, e ninguém chega lá por acaso.
 *
 * Pior: ela estava MORTA. `beforeinstallprompt` dispara uma vez por
 * carregamento, cedo, e o Chrome não o repete em navegação de SPA. Enquanto a
 * captura vivia dentro do hook — usado só por aquele cartão —, o evento chegava
 * ainda em `/login`, sem ninguém escutando, e o login navega por `navigate()`,
 * client-side, sem reload. O botão só aparecia para quem desse F5 estando em
 * `/settings`.
 *
 * É por isso que o teste principal aqui embaixo faz o percurso inteiro: dispara
 * o evento EM `/login` e só depois entra. Ele passa por causa da captura em
 * escopo de módulo (`src/lib/install.ts`, chamada em `main.tsx` antes do
 * `createRoot`), e falha com qualquer volta ao listener por montagem.
 *
 * O `beforeinstallprompt` é sintético: o Chromium do Playwright não dispara o de
 * verdade (ele depende do critério de instalabilidade e do servidor do Google).
 * O que está sendo medido é a NOSSA fiação — a captura, a travessia de rota e a
 * renderização —, não o navegador.
 */
const DISPARAR_EVENTO = () => {
  const evento = Object.assign(new Event('beforeinstallprompt'), {
    prompt: () => Promise.resolve(),
    userChoice: Promise.resolve({ outcome: 'accepted' }),
  });
  window.dispatchEvent(evento);
};

/** Cria a conta pela API, num contexto DESCARTADO: o teste precisa entrar pelo formulário. */
async function contaCriada(browser: Browser) {
  const email = `pwa${Date.now()}${Math.floor(Math.random() * 1000)}@e2e.com`;
  const senha = 'senha123';
  const ctx = await browser.newContext();
  await ctx.request.post(`${API}/auth/register`, {
    data: { name: 'Pedro PWA', email, password: senha },
  });
  // O `login` no meio NÃO é supérfluo: o cadastro não abre sessão, e sem ele o
  // POST de onboarding volta 401 em silêncio — a conta chega ao teste ainda
  // precisando de setup, o modal bloqueante cobre a barra superior, e o Radix
  // marca todo o resto da página como inerte. O botão fica no DOM, visível a
  // olho nu, e invisível para `getByRole`: uma falha de CENÁRIO que se disfarça
  // perfeitamente de "o componente não renderizou".
  await ctx.request.post(`${API}/auth/login`, { data: { email, password: senha } });
  await ctx.request.post(`${API}/auth/onboarding`, { data: { salary: 4000 } });
  await ctx.close();
  return { email, senha };
}

async function entrar(page: Page, email: string, senha: string) {
  await page.fill('#email', email);
  await page.fill('#password', senha);
  await page.getByRole('button', { name: /Acessar Conta|Autenticando/ }).click();
  await page.waitForURL(/\/overview/, { timeout: 15_000 });
}

test.describe('PWA — o botão de instalar na barra superior', () => {
  test('o evento chega em /login e o botão aparece depois de entrar', async ({ browser }) => {
    const { email, senha } = await contaCriada(browser);
    const context = await browser.newContext();
    const page = await context.newPage();

    await page.goto('/login');
    await expect(page.locator('#email')).toBeVisible();

    // O evento chega AQUI — na tela pública, antes de a casca do app existir.
    await page.evaluate(DISPARAR_EVENTO);

    await entrar(page, email, senha);

    const botao = page.getByRole('button', { name: 'Instalar aplicativo' });
    await expect(
      botao,
      'o evento disparado em /login foi perdido: a captura voltou a acontecer na montagem de um componente',
    ).toBeVisible();

    // E some quando o sistema avisa que instalou.
    await page.evaluate(() => window.dispatchEvent(new Event('appinstalled')));
    await expect(botao).toBeHidden();

    await context.close();
  });

  test('sem o evento do navegador, não há botão nenhum', async ({ browser }) => {
    // Um botão "Instalar" que não instala é pior do que não ter botão: no
    // Android sem o gancho ele abriria um diálogo que não existe.
    const { email, senha } = await contaCriada(browser);
    const context = await browser.newContext();
    const page = await context.newPage();

    await page.goto('/login');
    await entrar(page, email, senha);

    await expect(page.getByRole('button', { name: 'Instalar aplicativo' })).toHaveCount(0);
    await context.close();
  });

  test('com o botão na barra, a tela continua cabendo em 360px', async ({ browser }) => {
    /*
     * 360 e não os 393 do Pixel 5: é a largura em CSS px do Galaxy A e da linha
     * de entrada da Samsung — o piso que importa. Passar em 393 e estourar em
     * 360 é o cenário comum.
     *
     * Este portão precisa morar AQUI, e não no varredor de rotas de
     * `mobile_layout.mobile.spec.ts`: lá o botão nunca é renderizado, porque
     * ninguém dispara o `beforeinstallprompt`. A barra superior passa a ter
     * quatro coisas na mesma linha (seletor de escopo, botão, sino) e é
     * justamente onde o espaço acaba.
     */
    const { email, senha } = await contaCriada(browser);
    const context = await browser.newContext({ viewport: { width: 360, height: 760 } });
    const page = await context.newPage();

    await page.goto('/login');
    await page.evaluate(DISPARAR_EVENTO);
    await entrar(page, email, senha);
    await expect(page.getByRole('button', { name: 'Instalar aplicativo' })).toBeVisible();

    const excesso = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(excesso, `a barra superior com o botão estourou a largura em ${excesso}px`).toBeLessThanOrEqual(0);

    // A 360px o rótulo tem de estar ESCONDIDO (`hidden sm:inline`) — é o que
    // libera o espaço. O nome acessível, esse, continua o mesmo nas duas
    // larguras, porque vem de um `aria-label` fixo.
    await expect(page.getByText('Instalar app')).toBeHidden();

    await context.close();
  });
});
