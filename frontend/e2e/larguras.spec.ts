import { test, expect, type Page, type Browser } from '@playwright/test';

/*
 * O portão contra "o texto sumiu sem estourar nada".
 *
 * `mobile_layout.mobile.spec.ts` mede `scrollWidth` a 360px e é bom no que faz —
 * mas ele não tinha como pegar o pior defeito que a auditoria de UX encontrou:
 * a descrição do lançamento espremida até **zero pixel de largura** no celular.
 * Um `truncate` é `overflow: hidden`, e `overflow: hidden` zera a largura mínima
 * automática do item flex: o elemento cede até desaparecer **sem empurrar a
 * página**. Para o gate de rolagem horizontal, uma tela em que nenhum título é
 * legível é uma tela impecável.
 *
 * Aqui a pergunta é outra: *todo elemento que promete truncar ainda tem largura
 * suficiente para dizer alguma coisa?* Um `truncate` com 12px cabe em duas
 * letras e uma reticência; com 0px não cabe nem a reticência.
 *
 * ## Por que várias larguras
 *
 * O defeito do título aparecia em 14 de 15 linhas a 390px, em 2 de 15 a 412px e
 * em nenhuma a 430px. A lista de membros do espaço, por outro lado, só quebra
 * entre 768 e 1100px — largura que NENHUM teste do projeto media, e onde os
 * nomes ficavam com 0 a 24px ao lado dos controles de papel e do botão de
 * remover. As duas faixas precisam estar aqui, e nenhuma delas é "mobile".
 */
const API = 'http://localhost:8000/api/v1';

/** Menor largura em que um texto truncado ainda diz alguma coisa. */
const MINIMO_LEGIVEL = 40;

/**
 * As larguras, e o motivo de cada uma.
 *
 * Não é uma varredura: é uma lista curta de aparelhos e janelas reais, escolhida
 * para cobrir as duas faixas em que o produto já quebrou.
 */
const LARGURAS = [
  { largura: 360, altura: 800, nome: 'Galaxy A / Moto G' },
  { largura: 390, altura: 844, nome: 'iPhone 12–15' },
  { largura: 768, altura: 1024, nome: 'iPad retrato' },
  { largura: 1024, altura: 768, nome: 'iPad paisagem / janela dividida' },
  { largura: 1366, altura: 768, nome: 'notebook comum' },
];

async function contaComDados(browser: Browser, largura: number, altura: number) {
  const ts = Date.now() + Math.floor(Math.random() * 1000);
  const email = `larg${ts}@e2e.com`;
  const context = await browser.newContext({
    viewport: { width: largura, height: altura },
    isMobile: largura < 500,
    hasTouch: largura < 500,
  });
  const api = context.request;
  const ok = async (rotulo: string, resposta: Awaited<ReturnType<typeof api.post>>) => {
    expect(resposta.ok(), `semear ${rotulo}: ${resposta.status()} ${await resposta.text()}`).toBeTruthy();
  };

  await api.post(`${API}/auth/register`, { data: { name: 'Lia Larguras', email, password: 'senha123' } });
  await api.post(`${API}/auth/login`, { data: { email, password: 'senha123' } });
  await api.post(`${API}/auth/onboarding`, { data: { salary: 7000 } });
  const [ws] = await (await api.get(`${API}/workspaces/`)).json();
  const eu = await (await api.get(`${API}/auth/me`)).json();

  /*
   * Os lançamentos precisam nascer com `settled_at` nulo — é o que faz a pílula
   * "A pagar" existir. E é a SEGUNDA pílula que espreme o título até zero: as
   * linhas com uma pílula só sobreviviam, e por isso o defeito parecia
   * intermitente. Semear pago aqui seria semear o caso que não quebra.
   */
  for (const titulo of ['Café', 'Faxina', 'Mercado do mês inteiro com feira e açougue']) {
    await ok(`lançamento "${titulo}"`, await api.post(`${API}/workspaces/${ws.id}/transactions/`, {
      data: {
        title: titulo,
        total_amount: '220.00',
        transaction_date: new Date().toISOString(),
        payment_method: 'pix',
        settled: false,
        payers: [{ user_id: eu.id, amount: '220.00' }],
        splits: [{ user_id: eu.id, split_method: 'equal', input_value: '0' }],
      },
    }));
  }

  // Nome e e-mail COMPRIDOS: é o par que fica ilegível na faixa 768–1100, e um
  // convite pendente é a forma de tê-lo na tela sem precisar de um segundo login.
  await ok('convite', await api.post(`${API}/workspaces/${ws.id}/invites`, {
    data: { email: `bruno.nascimento.albuquerque.${ts}@exemplo-de-dominio.com.br`, role: 'member' },
  }));

  // Sem barra final: a coleção é registrada nas duas formas (`_colecao`), mas a
  // barra a mais é o caminho que já custou uma sessão perdida em 307 neste
  // projeto — não vale reintroduzir o hábito.
  await ok('conta de pagamento', await api.post(`${API}/me/payment-accounts`, {
    data: { name: 'Conta Corrente Itaú Personnalité — Agência 0912', type: 'checking' },
  }));

  return { context, wsId: ws.id as number };
}

/**
 * A tela RENDERIZOU alguma coisa?
 *
 * Esta verificação nasceu de um falso positivo real durante a implementação: um
 * comentário JSX mal colocado quebrou a compilação de `SettingsPage`, a rota
 * passou a mostrar só a tarja de erro do Vite — e o portão de truncamento ficou
 * VERDE, porque numa página sem conteúdo não há texto espremido nenhum.
 *
 * É a mesma armadilha que o gate de 360px já documenta noutro lugar: uma tabela
 * vazia cabe em qualquer largura. Medir "não achei defeito" numa tela que não
 * existe é o modo mais silencioso de um portão apodrecer.
 */
async function telaRenderizou(page: Page, onde: string) {
  const estado = await page.evaluate(() => ({
    overlayDoVite: !!document.querySelector('vite-error-overlay'),
    elementos: document.querySelectorAll('main *').length,
  }));
  expect(
    estado.overlayDoVite,
    `${onde}: a página está mostrando a tarja de erro do Vite — não há o que medir`,
  ).toBe(false);
  expect(
    estado.elementos,
    `${onde}: o <main> tem ${estado.elementos} elementos; a tela não chegou a renderizar `
    + 'e qualquer medida aqui seria um falso positivo',
  ).toBeGreaterThan(5);
}

async function esperarAssentar(page: Page) {
  await page.waitForLoadState('networkidle').catch(() => {});
  await expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0, { timeout: 10_000 }).catch(() => {});
  await page
    .waitForFunction(
      () =>
        document.getAnimations().every((a) => {
          if (a.playState !== 'running') return true;
          return ((a.effect?.getTiming().iterations ?? 1) as number) === Infinity;
        }),
      null,
      { timeout: 5_000 },
    )
    .catch(() => {});
}

/**
 * A medida.
 *
 * Duas condições, e as duas precisam valer ao mesmo tempo:
 *
 * 1. o texto está **de fato sendo cortado** (`scrollWidth > clientWidth`);
 * 2. o que sobrou é menor que o mínimo legível.
 *
 * A primeira condição não é detalhe: sem ela o portão acusava "Café" com 28px a
 * 1366px, onde a palavra cabe inteira e nada é perdido — `truncate` num texto
 * curto é só uma promessa que não precisou ser cumprida. O defeito é o par
 * "prometi reticências, cortei, e não sobrou largura nem para elas".
 *
 * `clientWidth`, e não `getBoundingClientRect().width`: é a largura interna, a
 * que de fato sobra para o texto depois do padding.
 */
async function semTextoEsmagado(page: Page, onde: string) {
  const esmagados = await page.evaluate((minimo) => {
    const fora: string[] = [];
    for (const el of Array.from(document.querySelectorAll<HTMLElement>('body *'))) {
      const cs = getComputedStyle(el);
      if (cs.textOverflow !== 'ellipsis') continue;
      if (cs.display === 'none' || cs.visibility === 'hidden') continue;
      const texto = (el.textContent ?? '').trim();
      if (!texto) continue;
      const r = el.getBoundingClientRect();
      // Elemento fora de vista (aba escondida, popup fechado) não é medido: ele
      // não tem largura porque não está na tela, e não porque foi espremido.
      if (r.width === 0 && r.height === 0) continue;
      if (el.scrollWidth <= el.clientWidth + 1) continue;
      if (el.clientWidth >= minimo) continue;
      const classe = typeof el.className === 'string' ? el.className.slice(0, 70) : '';
      fora.push(
        `<${el.tagName.toLowerCase()} class="${classe}"> `
        + `largura=${el.clientWidth}px (precisa de ${el.scrollWidth}px) texto="${texto.slice(0, 40)}"`,
      );
    }
    return fora.slice(0, 8);
  }, MINIMO_LEGIVEL);

  expect(
    esmagados,
    `${onde}: ${esmagados.length} texto(s) espremido(s) abaixo de ${MINIMO_LEGIVEL}px — `
    + `o elemento promete reticências mas não sobrou largura para nenhuma letra:\n  `
    + esmagados.join('\n  '),
  ).toEqual([]);
}

for (const { largura, altura, nome } of LARGURAS) {
  test(`textos não são espremidos a ${largura}px (${nome})`, async ({ browser }) => {
    test.setTimeout(120_000);
    const { context, wsId } = await contaComDados(browser, largura, altura);
    const page = await context.newPage();

    const rotas = [
      '/overview',
      '/me/accounts',
      '/me/payables',
      '/me/cards',
      '/me/commitments',
      '/me/ledger',
      '/me/settings',
      `/w/${wsId}`,
      `/w/${wsId}/transactions`,
      `/w/${wsId}/reports`,
      `/w/${wsId}/settings`,
    ];

    for (const rota of rotas) {
      await page.goto(rota);
      await esperarAssentar(page);
      await telaRenderizou(page, `${rota} a ${largura}px`);
      await semTextoEsmagado(page, `${rota} a ${largura}px`);
    }

    await context.close();
  });
}

/**
 * A ação principal de um diálogo tem de estar VISÍVEL quando ele abre.
 *
 * "Salvar Despesa" estava fora da janela em toda resolução menos 1920×1080 —
 * a 1366×768 ficava 150px abaixo da borda, e no celular 322px. O formulário mais
 * usado do produto abria sem mostrar o botão que o conclui, e nada media isso:
 * o diálogo tem rolagem própria, então ele não estoura a página.
 */
test('a ação principal do diálogo de despesa aparece sem rolar', async ({ browser }) => {
  test.setTimeout(120_000);
  for (const [largura, altura] of [[1366, 768], [390, 844]] as const) {
    const { context, wsId } = await contaComDados(browser, largura, altura);
    const page = await context.newPage();
    await page.goto(`/w/${wsId}/transactions`);
    await esperarAssentar(page);
    await page.getByRole('button', { name: /nova despesa/i }).first().click();
    const salvar = page.getByRole('button', { name: /salvar despesa/i });
    await expect(salvar).toBeVisible();
    await esperarAssentar(page);

    const dentro = await salvar.evaluate((el) => {
      const r = el.getBoundingClientRect();
      return { topo: Math.round(r.top), base: Math.round(r.bottom), janela: window.innerHeight };
    });
    expect(
      dentro.base <= dentro.janela && dentro.topo >= 0,
      `a ${largura}×${altura} o botão "Salvar Despesa" nasce em ${dentro.topo}–${dentro.base}px `
      + `numa janela de ${dentro.janela}px: é preciso rolar o diálogo para concluir o lançamento`,
    ).toBeTruthy();
    await context.close();
  }
});

/**
 * O "×" de fechar não pode cobrir conteúdo.
 *
 * Ele é `absolute right-2 top-2` e mede 40×40 — quer dizer que ele flutua por
 * cima do que estiver ali. No detalhe do lançamento, o que está ali é o VALOR da
 * despesa: medido, o botão ocupa x=870–910 e "−R$ 486,20" vai até x=898, no
 * desktop e no celular. O número mais importante do diálogo, com um ícone em
 * cima.
 *
 * O teste é geral de propósito: qualquer diálogo cujo cabeçalho chegue à borda
 * direita cai no mesmo defeito, e a lista de diálogos do app só cresce.
 */
async function nadaSobOBotaoDeFechar(page: Page, onde: string) {
  const colisoes = await page.evaluate(() => {
    const dialogo = document.querySelector('[role="dialog"]');
    if (!dialogo) return [];
    const fechar = [...dialogo.querySelectorAll('button')].find(
      (b) => getComputedStyle(b).position === 'absolute' && /fechar/i.test(b.textContent ?? ''),
    );
    if (!fechar) return [];
    const alvo = fechar.getBoundingClientRect();
    const achados: string[] = [];
    for (const el of Array.from(dialogo.querySelectorAll<HTMLElement>('*'))) {
      if (el === fechar || fechar.contains(el) || el.contains(fechar)) continue;
      if (el.children.length > 0) continue;              // só folhas de texto
      const texto = (el.textContent ?? '').trim();
      if (!texto) continue;
      const r = el.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) continue;
      const sobrepoe = !(
        r.right <= alvo.left || r.left >= alvo.right
        || r.bottom <= alvo.top || r.top >= alvo.bottom
      );
      if (sobrepoe) achados.push(`"${texto.slice(0, 30)}" em ${Math.round(r.left)}–${Math.round(r.right)}px`);
    }
    return achados.slice(0, 5);
  });

  expect(
    colisoes,
    `${onde}: o botão de fechar está por cima de ${colisoes.length} texto(s):\n  `
    + colisoes.join("\n  "),
  ).toEqual([]);
}

test('o botão de fechar não cobre o conteúdo do diálogo', async ({ browser }) => {
  test.setTimeout(120_000);
  for (const [largura, altura] of [[1366, 768], [390, 844]] as const) {
    const { context, wsId } = await contaComDados(browser, largura, altura);
    const page = await context.newPage();
    await page.goto(`/w/${wsId}/transactions`);
    await esperarAssentar(page);

    // Detalhe do lançamento: o cabeçalho tem título À ESQUERDA e valor À DIREITA,
    // e é o valor que estava embaixo do botão.
    await page.locator('[data-testid="ledger-row"] button').first().click();
    await esperarAssentar(page);
    await nadaSobOBotaoDeFechar(page, `detalhe do lançamento a ${largura}px`);
    await page.keyboard.press('Escape');

    await page.getByRole('button', { name: /nova despesa/i }).first().click();
    await esperarAssentar(page);
    await nadaSobOBotaoDeFechar(page, `nova despesa a ${largura}px`);

    await context.close();
  }
});
