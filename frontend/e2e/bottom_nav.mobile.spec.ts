import { test, expect, type Page } from '@playwright/test';

/*
 * A barra inferior do mobile — e o FAB que lançava despesa na casa errada.
 *
 * Este arquivo existe porque a suíte inteira rodava só em `Desktop Chrome`, e a
 * barra vive atrás de `md:hidden`. O teste de acessibilidade chega a AFIRMAR que
 * o Início global é somente leitura ("lançar despesa é ato de UMA casa, então o
 * botão não mora aqui") — e verificava isso num viewport onde o botão não é
 * renderizado de qualquer jeito. No mobile ele estava lá, em toda rota.
 *
 * O que a auditoria externa encontrou:
 *
 * 1. o FAB "Nova despesa" aparecia em `/overview` e em `/me/*`. Fora de
 *    `/w/:id` o diálogo usa o último workspace do `localStorage`, sem mostrar
 *    qual — a despesa ia para a casa errada sem que nada na tela dissesse isso;
 * 2. o terceiro slot primário apontava para `/w/:id/cards`, rota que deixou de
 *    existir no ADR 0021 (virou `/me/cards`). A `BottomNav` casa por igualdade e
 *    descarta o que não encontra: o item sumia da barra, calado.
 *
 * Roda no projeto `mobile` (Pixel 5) — ver `testMatch` em playwright.config.ts.
 */
const API = 'http://localhost:8000/api/v1';

async function contaNova(browser: Parameters<Parameters<typeof test>[1]>[0]['browser']) {
  const ts = Date.now() + Math.floor(Math.random() * 1000);
  const email = `mobile${ts}@e2e.com`;
  const context = await browser.newContext();
  await context.request.post(`${API}/auth/register`, {
    data: { name: 'Marina Mobile', email, password: 'senha123' },
  });
  await context.request.post(`${API}/auth/login`, {
    data: { email, password: 'senha123' },
  });
  await context.request.post(`${API}/auth/onboarding`, { data: { salary: 4000 } });
  return context;
}

/*
 * ---------------------------------------------------------------------------
 * A barra ESTÁ no rodapé? (e não só "existe no DOM")
 * ---------------------------------------------------------------------------
 *
 * Os três testes acima afirmam que os itens certos estão na barra. Nenhum deles
 * afirma onde a barra está — e a queixa de quem usa foi exatamente essa: "o
 * navbar de baixo não fica fixo, precisa rolar até o fim para aparecer",
 * inclusive no app instalado, onde não há barra de endereço retrátil para
 * culpar.
 *
 * Um elemento `position: fixed` deixa de resolver contra a viewport quando
 * QUALQUER ancestral cria um containing block — `transform`, `filter`,
 * `backdrop-filter`, `perspective`, `contain` ou `will-change` bastam, e
 * nenhum deles emite aviso: o elemento só passa a se comportar como
 * `absolute` e vai parar no fim do documento. É a família de defeito que só um
 * teste que MEDE encontra, e é por isso que o diagnóstico abaixo aponta o
 * ancestral culpado em vez de dizer apenas "não está visível".
 */
async function medirBarra(page: Page) {
  return page.locator('nav').last().evaluate((nav: HTMLElement) => {
    const criaContainingBlock = (s: CSSStyleDeclaration) => {
      const nulo = (v: string | null | undefined) => !v || v === 'none' || v === 'auto';
      return (
        !nulo(s.transform)
        || !nulo(s.filter)
        || !nulo(s.backdropFilter)
        || !nulo(s.perspective)
        || !nulo(s.willChange)
        || /paint|layout|strict|content/.test(s.contain ?? '')
      );
    };

    let culpado: string | null = null;
    for (let p = nav.parentElement; p && p !== document.documentElement; p = p.parentElement) {
      const s = getComputedStyle(p);
      if (!criaContainingBlock(s)) continue;
      const classe = typeof p.className === 'string' ? p.className.slice(0, 70) : '';
      culpado =
        `<${p.tagName.toLowerCase()} class="${classe}"> `
        + `transform=${s.transform} filter=${s.filter} `
        + `backdrop-filter=${s.backdropFilter} contain=${s.contain} will-change=${s.willChange}`;
      break;
    }

    const r = nav.getBoundingClientRect();
    const estilo = getComputedStyle(nav);
    return {
      position: estilo.position,
      display: estilo.display,
      topo: Math.round(r.top),
      base: Math.round(r.bottom),
      altura: Math.round(r.height),
      innerHeight: window.innerHeight,
      visual: Math.round(window.visualViewport?.height ?? window.innerHeight),
      scrollY: Math.round(window.scrollY),
      alturaDoDocumento: document.documentElement.scrollHeight,
      culpado,
    };
  });
}

/**
 * `+2` de tolerância, e não zero: sob emulação de aparelho (`isMobile: true`) o
 * Chromium mantém um viewport visual separado do de layout, e um `fixed` se
 * dimensiona pelo visual. O portão de largura já tinha levado uma acusação
 * falsa por comparar contra a constante errada (ver o comentário em
 * `mobile_layout.mobile.spec.ts:74`); aqui a régua é a medida, com folga de
 * subpixel.
 */
async function barraNoRodape(page: Page, onde: string) {
  await page.evaluate(() => window.scrollTo(0, 0));
  // As animações de entrada (`animate-in`, 300ms no `<main>` e 700ms na tela de
  // Configurações) aplicam `transform` enquanto rodam. Medir no meio delas mede
  // um estado que não existe parado.
  await page.waitForTimeout(800);

  const m = await medirBarra(page);
  const relato =
    `${onde}: a barra inferior não está no rodapé da viewport.\n`
    + `  position=${m.position} display=${m.display}\n`
    + `  topo=${m.topo} base=${m.base} altura=${m.altura}\n`
    + `  innerHeight=${m.innerHeight} visualViewport=${m.visual} scrollY=${m.scrollY}\n`
    + `  alturaDoDocumento=${m.alturaDoDocumento}\n`
    + `  ancestral que cria containing block: ${m.culpado ?? 'nenhum'}`;

  expect(m.position, relato).toBe('fixed');
  expect(m.culpado, relato).toBeNull();
  // O que a pessoa reclamou, em números: com a página no topo, a base da barra
  // tem de estar DENTRO da tela — não abaixo dela, esperando uma rolagem.
  expect(m.base, relato).toBeLessThanOrEqual(m.innerHeight + 2);
  expect(m.topo, relato).toBeGreaterThan(0);
}

test.describe('BottomNav — posição (mobile)', () => {
  test('a barra fica no rodapé sem precisar rolar', async ({ browser }) => {
    test.setTimeout(120_000);
    const context = await contaNova(browser);
    const [ws] = await (await context.request.get(`${API}/workspaces/`)).json();
    const eu = await (await context.request.get(`${API}/auth/me`)).json();

    // Página LONGA de propósito. Numa tela curta a barra cabe por acidente, e
    // foi assim que o defeito atravessou a suíte: os testes de navegação abrem
    // `/w/:id` recém-criado, que é quase vazio.
    //
    // O `expect` na resposta não é zelo: sem `payers` a rota devolve 422 e a
    // semeadura vira um laço que não cria nada — foi exatamente o que estava
    // acontecendo, calado, na fixture do portão de largura.
    for (let i = 0; i < 18; i += 1) {
      const r = await context.request.post(`${API}/workspaces/${ws.id}/transactions/`, {
        data: {
          title: `Despesa de teste ${i + 1} com título comprido para ocupar linha`,
          total_amount: '123.45',
          transaction_date: new Date().toISOString(),
          payment_method: 'pix',
          payers: [{ user_id: eu.id, amount: '123.45' }],
          splits: [{ user_id: eu.id, split_method: 'equal', input_value: '0' }],
        },
      });
      expect(r.ok(), `semear lançamento ${i + 1}: ${await r.text()}`).toBeTruthy();
    }

    const page = await context.newPage();
    await page.goto(`/w/${ws.id}/transactions`);
    await page.waitForLoadState('networkidle').catch(() => {});
    await barraNoRodape(page, '/w/:id/transactions (página longa)');

    // E o teste não pode ser vácuo: se a página não rola, "sem rolar" não
    // afirma nada.
    const alturas = await page.evaluate(() => ({
      documento: document.documentElement.scrollHeight,
      janela: window.innerHeight,
      visual: Math.round(window.visualViewport?.height ?? window.innerHeight),
    }));
    expect(
      alturas.documento - alturas.janela,
      `a página de lançamentos precisa rolar para o teste valer `
        + `(documento=${alturas.documento} janela=${alturas.janela} visual=${alturas.visual})`,
    ).toBeGreaterThan(50);

    // Tela CURTA: aqui é pior que inconveniente. Se a barra cai abaixo da
    // dobra numa página que não rola, ela fica literalmente inalcançável.
    await page.goto('/me/financing');
    await page.waitForLoadState('networkidle').catch(() => {});
    await barraNoRodape(page, '/me/financing (página curta)');

    // E depois de rolar até o fim e voltar, continua onde deveria.
    await page.goto(`/w/${ws.id}/transactions`);
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await page.waitForTimeout(300);
    const noFim = await medirBarra(page);
    expect(
      noFim.base,
      `rolando até o fim: base=${noFim.base} innerHeight=${noFim.innerHeight}`,
    ).toBeLessThanOrEqual(noFim.innerHeight + 2);

    await context.close();
  });

  test('a faixa de convite pendente não fica presa na barra superior', async ({ browser }) => {
    test.setTimeout(120_000);
    const ts = Date.now() + Math.floor(Math.random() * 1000);

    // Quem convida.
    const anfitria = await contaNova(browser);
    const [ws] = await (await anfitria.request.get(`${API}/workspaces/`)).json();

    // Quem é convidada — e que verá a faixa.
    const convidadaEmail = `convidada${ts}@e2e.com`;
    const convidada = await browser.newContext();
    await convidada.request.post(`${API}/auth/register`, {
      data: { name: 'Bruna Convidada', email: convidadaEmail, password: 'senha123' },
    });
    await convidada.request.post(`${API}/auth/login`, {
      data: { email: convidadaEmail, password: 'senha123' },
    });
    await convidada.request.post(`${API}/auth/onboarding`, { data: { salary: 3000 } });

    const convite = await anfitria.request.post(`${API}/workspaces/${ws.id}/invites`, {
      data: { email: convidadaEmail, role: 'member' },
    });
    expect(convite.ok(), await convite.text()).toBeTruthy();

    const page = await convidada.newPage();
    await page.goto('/overview');
    await page.waitForLoadState('networkidle').catch(() => {});

    // O modal de convite abre sozinho depois do onboarding; a faixa é o que
    // sobra DEPOIS de "Depois" — e é ela que tem de continuar alcançável.
    const modal = page.getByRole('dialog');
    await expect(modal).toBeVisible();
    await modal.getByRole('button', { name: /Depois/i }).click();
    await expect(modal).toBeHidden();

    const faixa = page.getByRole('button', { name: /Convite para|convites esperando/ });
    await expect(faixa).toBeVisible();
    await page.waitForTimeout(500);

    /*
     * A faixa é `fixed inset-x-3 bottom-20`, mas mora dentro da barra
     * superior, que tem `backdrop-blur-sm` — e `backdrop-filter` cria
     * containing block para descendentes `fixed`. O `bottom: 5rem` resolvia
     * contra a caixa de ~40px da topbar, ou seja, a faixa era desenhada ACIMA
     * do topo da tela. O aviso que "precisa estar visível de qualquer tela"
     * não estava visível em tela nenhuma do celular.
     */
    const caixa = await faixa.evaluate((el: HTMLElement) => {
      const r = el.getBoundingClientRect();
      return { topo: Math.round(r.top), base: Math.round(r.bottom), altura: window.innerHeight };
    });
    const relato = `faixa de convite: topo=${caixa.topo} base=${caixa.base} innerHeight=${caixa.altura}`;
    expect(caixa.topo, relato).toBeGreaterThan(0);
    expect(caixa.base, relato).toBeLessThanOrEqual(caixa.altura + 2);
    // E na METADE DE BAIXO da tela: é onde o `bottom-20` a coloca quando
    // resolve contra a viewport, que é o ponto do conserto.
    expect(caixa.topo, relato).toBeGreaterThan(caixa.altura / 2);

    await page.close();
    await convidada.close();
    await anfitria.close();
  });
});

test.describe('BottomNav (mobile)', () => {
  test('o FAB só existe dentro de um workspace', async ({ browser }) => {
    const context = await contaNova(browser);
    const [ws] = await (await context.request.get(`${API}/workspaces/`)).json();
    const page = await context.newPage();

    // Dentro do workspace: o botão existe e é o caminho de lançar.
    await page.goto(`/w/${ws.id}`);
    const fab = page.locator('nav').getByRole('button', { name: 'Nova despesa' });
    await expect(fab).toBeVisible();

    // Visitar o workspace deixa o "último visitado" no localStorage — é
    // exatamente esse estado que fazia o FAB parecer utilizável na visão global.
    await page.goto('/overview');
    await expect(page.getByRole('heading', { name: /Seu mês/ })).toBeVisible();
    await expect(fab).toHaveCount(0);

    await page.goto('/me/cards');
    await expect(fab).toHaveCount(0);

    await context.close();
  });

  test('todos os slots primários aparecem na barra', async ({ browser }) => {
    const context = await contaNova(browser);
    const [ws] = await (await context.request.get(`${API}/workspaces/`)).json();
    const page = await context.newPage();
    await page.goto(`/w/${ws.id}`);

    const barra = page.locator('nav').last();
    // Três slots + "Mais", com os rótulos de `nav-items.ts`. O de Cartões sumia
    // porque apontava para uma rota morta, e a filtragem silenciosa não deixava
    // rastro — a barra simplesmente vinha com um item a menos.
    for (const rotulo of ['Seu mês', 'Lançamentos', 'Cartões', 'Mais']) {
      await expect(barra.getByText(rotulo, { exact: true })).toBeVisible();
    }

    await barra.getByText('Cartões', { exact: true }).click();
    await expect(page).toHaveURL(/\/me\/cards$/);

    await context.close();
  });

  test('o sheet "Mais" alcança as configurações pessoais', async ({ browser }) => {
    const context = await contaNova(browser);
    const [ws] = await (await context.request.get(`${API}/workspaces/`)).json();
    const page = await context.newPage();
    await page.goto(`/w/${ws.id}`);

    await page.locator('nav').last().getByText('Mais', { exact: true }).click();
    const sheet = page.getByRole('dialog');
    await expect(sheet).toBeVisible();
    // Perfil, senha e aparência viviam presos em `/w/:id/settings` — quem
    // ficasse sem workspace válido não os alcançava.
    await sheet.getByText('Suas configurações', { exact: true }).click();
    await expect(page).toHaveURL(/\/me\/settings$/);

    await context.close();
  });
});
