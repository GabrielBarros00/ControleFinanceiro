import { test, expect, type Page } from '@playwright/test';

/*
 * O portão contra "a tela ficou maior do que deveria".
 *
 * Não existia asserção NENHUMA de largura no repositório (um `grep` por
 * `scrollWidth` voltava vazio), e o resultado era previsível: quatro telas
 * estouravam a viewport do celular ao mesmo tempo, e as capturas do catálogo
 * cobriam só cinco rotas — nenhuma delas entre as quebradas.
 *
 * A causa raiz quase sempre é a mesma família: um bloco `shrink-0` sem
 * `flex-wrap`, uma lista de abas sem rolagem, uma largura mínima em px maior que
 * a tela. Nenhuma dessas dá erro; a página só ganha rolagem lateral e o
 * conteúdo importante sai de vista. Só um teste que MEDE encontra.
 *
 * **360px, e não os 393 do Pixel 5**: 360 é a largura em CSS px do Galaxy A,
 * do Moto G e de boa parte dos Android em uso — a mais estreita que ainda
 * importa. Passar em 393 e quebrar em 360 é o cenário comum.
 *
 * Roda no projeto `mobile` (ver `testMatch` em playwright.config.ts).
 */
const API = 'http://localhost:8000/api/v1';
const LARGURA = 360;

async function contaComDados(browser: Parameters<Parameters<typeof test>[1]>[0]['browser']) {
  const ts = Date.now() + Math.floor(Math.random() * 1000);
  const email = `layout${ts}@e2e.com`;
  const context = await browser.newContext();
  const api = context.request;
  await api.post(`${API}/auth/register`, {
    data: { name: 'Lara Layout', email, password: 'senha123' },
  });
  await api.post(`${API}/auth/login`, { data: { email, password: 'senha123' } });
  await api.post(`${API}/auth/onboarding`, { data: { salary: 4000 } });
  const [ws] = await (await api.get(`${API}/workspaces/`)).json();
  const eu = await (await api.get(`${API}/auth/me`)).json();

  /*
   * O lançamento precisa de `payers` — e é por isso que existe o `expect` logo
   * abaixo.
   *
   * A versão anterior desta fixture postava sem `payers` e IGNORAVA a resposta.
   * O corpo voltava 422 ("Field required"), nenhum lançamento era criado, e o
   * portão passou a medir uma conta vazia enquanto o comentário logo acima
   * afirmava, em bom português, que semeava "texto longo e valor alto de
   * propósito". O portão continuou verde e deixou de medir o que dizia medir —
   * é a forma mais silenciosa de um gate apodrecer, e a única defesa é conferir
   * o código de resposta da semeadura.
   */
  const semear = async (rotulo: string, resposta: Awaited<ReturnType<typeof api.post>>) => {
    expect(resposta.ok(), `semear ${rotulo}: ${await resposta.text()}`).toBeTruthy();
  };

  // Dado com TEXTO LONGO e VALOR ALTO de propósito: uma tela vazia cabe em
  // qualquer largura, e foi assim que o problema passou despercebido. O que
  // estoura é o título que não quebra e o número que não encolhe.
  await semear('renda', await api.post(`${API}/me/income`, {
    data: {
      title: 'Salário — Consultoria Internacional de Tecnologia Ltda.',
      amount: '187450.90',
      received_at: new Date().toISOString(),
    },
  }));
  await semear('lançamento', await api.post(`${API}/workspaces/${ws.id}/transactions/`, {
    data: {
      title: 'Matrícula e mensalidade anual da escola bilíngue das crianças',
      total_amount: '94800.00',
      transaction_date: new Date().toISOString(),
      payment_method: 'pix',
      payers: [{ user_id: eu.id, amount: '94800.00' }],
      splits: [{ user_id: eu.id, split_method: 'equal', input_value: '0' }],
    },
  }));

  /*
   * Linhas nas tabelas que a versão anterior deste portão nunca chegou a medir.
   *
   * As abas de Auditoria, Categorias e Convites ficavam de fora porque só a aba
   * PADRÃO de cada tela era visitada — e, mesmo que fossem visitadas, estariam
   * vazias: a conta acima nascia com um lançamento e nada mais. Uma tabela sem
   * linha nenhuma cabe em qualquer largura, que é a mesma armadilha registrada
   * no comentário do bloco acima, um nível abaixo.
   *
   * Cada chamada aqui existe por um motivo de LARGURA, não de cobertura:
   *   - lançamentos e convites gravam trilha de auditoria (a aba `audit` é
   *     read-only: não há como semeá-la direto, e criar categoria NÃO é uma
   *     ação auditada);
   *   - o convite por e-mail preenche a lista de convites com um endereço
   *     longo, que é o texto que não quebra;
   *   - a categoria com nome comprido é a célula que empurra a tabela.
   *
   * O nome do espaço NÃO é alterado aqui de propósito: o `ScopeSwitcher` mostra
   * o nome do espaço atual, e os testes de escopo lá embaixo procuram o botão
   * por "Meu espaço". Renomear na fixture compartilhada os derrubava.
   */
  // Sem barra final: `categories` é registrada como `""` no roteador. Com a
  // barra, o Starlette responde 307 e o cookie de sessão não acompanha o
  // redirecionamento — o pedido chega deslogado.
  for (const nome of [
    'Educação e material escolar das crianças',
    'Manutenção do apartamento e condomínio',
    'Assinaturas digitais recorrentes',
  ]) {
    await semear(`categoria "${nome}"`, await api.post(`${API}/workspaces/${ws.id}/categories`, {
      data: { name: nome, color: '#8b5cf6' },
    }));
  }
  for (let i = 0; i < 4; i += 1) {
    await semear(`lançamento ${i + 1}`, await api.post(`${API}/workspaces/${ws.id}/transactions/`, {
      data: {
        title: `Compra parcelada de eletrodomésticos da cozinha — parcela ${i + 1}`,
        total_amount: '2390.00',
        transaction_date: new Date().toISOString(),
        payment_method: 'pix',
        payers: [{ user_id: eu.id, amount: '2390.00' }],
        splits: [{ user_id: eu.id, split_method: 'equal', input_value: '0' }],
      },
    }));
  }
  for (const prefixo of ['convidada.com.endereco.comprido', 'segunda.pessoa.convidada.aqui']) {
    await semear('convite', await api.post(`${API}/workspaces/${ws.id}/invites`, {
      data: { email: `${prefixo}${ts}@exemplo-de-dominio.com.br`, role: 'member' },
    }));
  }

  // Link de convite: dá acesso a `/invite/:token`, uma rota pública-para-logado
  // que o portão nunca mediu.
  const link = await api.post(`${API}/workspaces/${ws.id}/invites/link`, {
    data: { role: 'member' },
  });
  await semear('link de convite', link);
  const token = (await link.json()).token as string;

  return { context, wsId: ws.id as number, conviteToken: token };
}

/**
 * Mede TODAS as abas de uma tela, não só a que abre por padrão.
 *
 * Este era o maior buraco do portão: `/w/:id/settings` abre em "Espaço e
 * membros", `/me/settings` abre em "Perfil" e `/admin` abre em "Visão geral" —
 * então Auditoria, Categorias, Contas, Convites, Aparência, Pessoas e Saúde
 * nunca foram medidas a 360px. As duas telas que a pessoa reportou como
 * quebradas estavam exatamente nesse conjunto.
 *
 * `papel` distingue os dois mecanismos de aba do app: `SettingsShell` usa
 * botões numa faixa rolável; `/admin` usa Radix Tabs (`role="tab"`).
 */
async function medirAbas(
  page: Page,
  rota: string,
  abas: string[],
  papel: 'button' | 'tab' = 'button',
) {
  for (const aba of abas) {
    const alvo = page.getByRole(papel, { name: aba, exact: true }).first();
    await alvo.click();
    // A troca de aba dispara `animate-in` (300–700ms) e o `transform` do
    // `slide-in` move o conteúdo para fora da viewport enquanto roda.
    await page.waitForTimeout(800);
    await semRolagemHorizontal(page, `${rota} › aba "${aba}"`);
  }
}

/**
 * A medida.
 *
 * `documentElement.scrollWidth` e não `body`: o `body` pode ter largura própria
 * e esconder um filho que estoura. `+1` de tolerância porque um subpixel de
 * arredondamento em borda/sombra não é defeito de layout.
 *
 * Quando falha, a mensagem lista os elementos culpados — sem isso o teste diz
 * "a página tem 412px" e alguém passa meia hora procurando qual dos duzentos
 * nós é o responsável.
 */
async function semRolagemHorizontal(page: Page, rota: string) {
  const diagnostico = await page.evaluate(() => {
    const doc = document.documentElement;
    const excesso = doc.scrollWidth - doc.clientWidth;

    /*
     * A régua é o `clientWidth` MEDIDO, não a constante do teste.
     *
     * Sob emulação de aparelho (`isMobile: true`) o Chromium mantém um viewport
     * visual separado do de layout, e um `position: fixed` se dimensiona pelo
     * visual. Numa falha no CI do Linux, a barra inferior — que é
     * `fixed inset-x-0` e por definição não estoura nada — apareceu na lista de
     * culpados com `direita=364` enquanto o teste dizia "a 360px". A constante
     * era a errada, não o elemento: comparar contra ela produzia acusação falsa
     * e escondia o culpado real no meio do ruído.
     */
    const largura = doc.clientWidth;

    const excedentes: HTMLElement[] = [];
    const recortados: HTMLElement[] = [];
    if (excesso > 1) {
      for (const el of Array.from(document.querySelectorAll<HTMLElement>('body *'))) {
        const r = el.getBoundingClientRect();
        if (r.width === 0) continue;
        if (r.right <= largura + 1) continue;

        /*
         * Separa quem está DENTRO de um container que recorta na horizontal.
         *
         * Uma aba fora de vista dentro de uma faixa `overflow-x-auto` é o
         * comportamento pretendido, não um defeito — ela é recortada pelo
         * container e não empurra a página. Sem esta separação, cada faixa de
         * abas despejava seus cinco filhos na lista e o culpado real ficava de
         * fora do limite de seis.
         *
         * Mas o recortado não é descartado: ele vai para uma segunda lista. Um
         * `overflow-hidden` zera a largura MÍNIMA automática do próprio
         * contêiner, e não do conteúdo — então quando um cartão inteiro estoura
         * é lá dentro que está o texto que não quebra, e a primeira lista, que
         * só enxerga contêineres esticados, não tem como dizer qual é.
         */
        let recortado = false;
        for (let p = el.parentElement; p && p !== doc; p = p.parentElement) {
          const overflow = getComputedStyle(p).overflowX;
          if (overflow === 'auto' || overflow === 'scroll' || overflow === 'hidden') {
            recortado = true;
            break;
          }
        }
        (recortado ? recortados : excedentes).push(el);
      }
    }

    /*
     * Só as FOLHAS.
     *
     * Um elemento largo demais estica todos os ancestrais, e `querySelectorAll`
     * devolve em ordem de documento — então a lista começava pelo `<main>`, pelo
     * `<aside>` e pelos cartões, e o limite de seis se esgotava antes de chegar
     * ao nó que realmente não cabe. Numa falha real de `/w/:id/settings` os seis
     * nomes eram seis contêineres, todos com a mesma `direita=701`, e nenhum
     * deles era acionável.
     *
     * Quem tem descendente também excedente é, por construção, apenas a vítima.
     */
    const soAsFolhas = (lista: HTMLElement[]) =>
      lista.filter((el) => !lista.some((outro) => outro !== el && el.contains(outro)));
    const folhas = soAsFolhas(excedentes);
    const descrever = (el: HTMLElement) => {
      const classe = typeof el.className === 'string' ? el.className.slice(0, 90) : '';
      const texto = (el.textContent ?? '').trim().replace(/\s+/g, ' ').slice(0, 40);
      const r = el.getBoundingClientRect();
      return (
        `<${el.tagName.toLowerCase()} class="${classe}"> `
        + `direita=${Math.round(r.right)} largura=${Math.round(r.width)}`
        + (texto ? ` texto="${texto}"` : '')
      );
    };

    return {
      excesso,
      culpados: folhas.slice(0, 6).map(descrever),
      recortados: soAsFolhas(recortados).slice(0, 6).map(descrever),
      largura,
      innerWidth: window.innerWidth,
    };
  });

  expect(
    diagnostico.excesso,
    `${rota} rola ${diagnostico.excesso}px na horizontal.\n`
      + `Viewport de layout: ${diagnostico.largura}px (window.innerWidth: ${diagnostico.innerWidth}px).\n`
      + `Prováveis culpados:\n  ${diagnostico.culpados.join('\n  ')}\n`
      + `Conteúdo largo dentro de contêiner que recorta:\n  ${diagnostico.recortados.join('\n  ')}`,
  ).toBeLessThanOrEqual(1);
}

test.describe('Layout mobile — nenhuma tela estoura a largura', () => {
  test('todas as rotas autenticadas cabem em 360px', async ({ browser }) => {
    test.setTimeout(180_000);
    const { context, wsId } = await contaComDados(browser);
    const page = await context.newPage();
    await page.setViewportSize({ width: LARGURA, height: 780 });

    // Os caminhos CANÔNICOS (os aliases legados só redirecionam). Mesma lista
    // do roteiro de capturas — se uma rota nova entrar lá, entra aqui também.
    const rotas = [
      '/overview',
      '/me/payables',
      '/me/income',
      '/me/cards',
      '/me/financing',
      '/me/commitments',
      '/me/settlements',
      '/me/reports',
      '/me/ledger',
      '/me/settings',
      `/w/${wsId}`,
      `/w/${wsId}/transactions`,
      `/w/${wsId}/payables`,
      `/w/${wsId}/reports`,
      `/w/${wsId}/recurring`,
      `/w/${wsId}/debts`,
      `/w/${wsId}/import`,
      `/w/${wsId}/settings`,
    ];

    for (const rota of rotas) {
      await page.goto(rota);
      await page.waitForLoadState('networkidle').catch(() => {});
      // As animações de entrada movem elementos para fora da viewport durante
      // o `slide-in`; medir no meio delas acusa estouro que não existe parado.
      await page.waitForTimeout(700);
      await semRolagemHorizontal(page, rota);
    }

    await context.close();
  });

  test('todas as ABAS das telas de configuração cabem em 360px', async ({ browser }) => {
    test.setTimeout(180_000);
    const { context, wsId } = await contaComDados(browser);
    const page = await context.newPage();
    await page.setViewportSize({ width: LARGURA, height: 780 });

    // Configurações do ESPAÇO. "Auditoria" só existe para admin/owner — a conta
    // criou o espaço, então é dona.
    await page.goto(`/w/${wsId}/settings`);
    await page.waitForLoadState('networkidle').catch(() => {});
    await medirAbas(page, `/w/${wsId}/settings`, ['Categorias', 'Auditoria', 'Espaço e membros']);

    // Configurações PESSOAIS.
    await page.goto('/me/settings');
    await page.waitForLoadState('networkidle').catch(() => {});
    await medirAbas(page, '/me/settings', [
      'Segurança', 'Contas', 'Convidar alguém', 'Aparência', 'Perfil',
    ]);

    await context.close();
  });

  /*
   * Acertos — as duas telas, as três abas e o que está RECOLHIDO nelas.
   *
   * A varredura de rotas acima abre cada tela na aba inicial (Resumo), e desde o
   * redesenho o conteúdo mais largo do app não está nela: a tabela de despesas
   * do mês (cinco colunas, com chips de rateio) nasce dentro de um `<details>`
   * fechado. Fechado, ele não pode estourar nada — e é exatamente por isso que
   * medi-lo fechado não prova coisa alguma. O mesmo vale para "De onde vem esse
   * saldo" e "Entre outras pessoas".
   */
  test('as abas de Acertos cabem em 360px, inclusive o que vem recolhido', async ({ browser }) => {
    test.setTimeout(180_000);
    const { context, wsId } = await contaComDados(browser);
    const page = await context.newPage();
    await page.setViewportSize({ width: LARGURA, height: 780 });

    for (const rota of [`/w/${wsId}/debts`, '/me/settlements']) {
      await page.goto(rota);
      await page.waitForLoadState('networkidle').catch(() => {});
      await page.waitForTimeout(700);
      await medirAbas(page, rota, ['Resumo', 'Por mês', 'Histórico'], 'tab');

      // Tudo o que está atrás de um `<details>`, aberto de uma vez: é o estado
      // em que a pessoa realmente lê a tabela larga.
      let abertos = 0;
      for (const aba of ['Resumo', 'Por mês']) {
        await page.getByRole('tab', { name: aba, exact: true }).first().click();
        await page.waitForTimeout(800);
        const blocos = page.locator('details:not([open]) > summary');
        for (let i = await blocos.count(); i > 0; i--) {
          await blocos.first().click();
          await page.waitForTimeout(200);
          abertos++;
        }
        await semRolagemHorizontal(page, `${rota} › aba "${aba}" com tudo aberto`);
      }
      // Sem esta linha o teste passa por VACUIDADE: se um dia o `<details>` sair
      // (ou a semeadura deixar de produzir despesa), o laço acima não abre nada,
      // a medição recai sobre a tela recolhida e o gate segue verde protegendo o
      // nada. Foi assim que `smoke_prod` e `e2e-prod` apodreceram.
      expect(abertos, `${rota} não tinha bloco recolhido para abrir`).toBeGreaterThan(0);
    }

    await context.close();
  });

  test('a tela de convite cabe em 360px', async ({ browser }) => {
    const { context, conviteToken } = await contaComDados(browser);
    expect(conviteToken, 'o link de convite não foi emitido').toBeTruthy();
    const page = await context.newPage();
    await page.setViewportSize({ width: LARGURA, height: 780 });

    await page.goto(`/invite/${conviteToken}`);
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.waitForTimeout(700);
    await semRolagemHorizontal(page, '/invite/:token');

    await context.close();
  });

  /*
   * `/admin` — a tela mais densa do site (tabela de sete colunas, seis abas) e a
   * única que o portão nunca visitou. Precisa de superadministrador, e o único
   * caminho de teste é a JANELA DE BOOTSTRAP: `SUPERADMIN_EMAIL` está no env do
   * backend do e2e (`scripts/e2e.mjs`), e a primeira conta com aquele endereço
   * nasce com o papel.
   *
   * O mesmo e-mail é usado por `a11y.spec.ts`, que roda no projeto `chromium`.
   * Os dois projetos podem correr em paralelo contra o MESMO backend, então o
   * cadastro aqui é "tenta e ignora": quem chegar primeiro cria, quem chegar
   * depois só entra. O que não pode falhar em silêncio é o papel — se não vier
   * `superadmin`, a rota devolve uma tela de erro que cabe em qualquer largura
   * e o portão passaria sem medir nada.
   */
  test('a Administração do site cabe em 360px', async ({ browser }) => {
    test.setTimeout(180_000);
    const context = await browser.newContext();
    const email = 'admin-a11y@e2e.com';
    await context.request.post(`${API}/auth/register`, {
      data: { name: 'Admin Layout', email, password: 'senha123' },
    });
    await context.request.post(`${API}/auth/login`, { data: { email, password: 'senha123' } });
    await context.request.post(`${API}/auth/onboarding`, { data: { salary: 4000 } });
    const eu = await (await context.request.get(`${API}/auth/me`)).json();
    expect(
      eu.platform_role,
      `a conta de bootstrap não é superadmin (papel: ${JSON.stringify(eu)})`,
    ).toBe('superadmin');

    const page = await context.newPage();
    await page.setViewportSize({ width: LARGURA, height: 780 });
    await page.goto('/admin');
    // Timeout folgado: `/admin` é `React.lazy` e o servidor de desenvolvimento
    // compila o chunk na primeira visita.
    await expect(page.getByRole('heading', { name: /Administração/i })).toBeVisible({
      timeout: 30_000,
    });
    await page.waitForTimeout(700);
    await semRolagemHorizontal(page, '/admin');
    await medirAbas(
      page,
      '/admin',
      ['Pessoas', 'Convites', 'Configurações', 'Saúde', 'Auditoria'],
      'tab',
    );

    await context.close();
  });

  test('as telas públicas cabem em 360px', async ({ browser }) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    await page.setViewportSize({ width: LARGURA, height: 780 });
    for (const rota of ['/login', '/register', '/forgot-password', '/reset-password']) {
      await page.goto(rota);
      await page.waitForLoadState('networkidle').catch(() => {});
      await page.waitForTimeout(500);
      await semRolagemHorizontal(page, rota);
    }
    await context.close();
  });

  test('os diálogos e as gavetas cabem em 360px', async ({ browser }) => {
    test.setTimeout(120_000);
    const { context, wsId } = await contaComDados(browser);
    const page = await context.newPage();
    await page.setViewportSize({ width: LARGURA, height: 780 });

    // Nova despesa — o formulário mais denso do app, e bottom sheet no celular.
    await page.goto(`/w/${wsId}/transactions`);
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.locator('nav').last().getByRole('button', { name: 'Nova despesa' }).click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.getByRole('dialog').getByRole('button', { name: /Opções avançadas/ }).click();
    await page.waitForTimeout(600);
    await semRolagemHorizontal(page, 'diálogo Nova despesa');
    await page.keyboard.press('Escape');
    await page.waitForTimeout(400);

    // Gaveta "Mais" — a navegação inteira do celular.
    await page.locator('nav').last().getByText('Mais', { exact: true }).click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.waitForTimeout(500);
    await semRolagemHorizontal(page, 'gaveta Mais');
    await page.keyboard.press('Escape');
    await page.waitForTimeout(400);

    // Gaveta de filtros — só existe abaixo de `sm`.
    await page.getByRole('button', { name: /^Filtros/ }).click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.waitForTimeout(500);
    await semRolagemHorizontal(page, 'gaveta Filtros');

    await context.close();
  });
});

test.describe('Escopo no celular — pessoal × compartilhado', () => {
  test('a gaveta "Mais" separa o que é seu do que é do espaço', async ({ browser }) => {
    const { context, wsId } = await contaComDados(browser);
    const page = await context.newPage();
    await page.goto(`/w/${wsId}`);

    await page.locator('nav').last().getByText('Mais', { exact: true }).click();
    const gaveta = page.getByRole('dialog');
    await expect(gaveta).toBeVisible();

    /*
     * A gaveta chamava `navFlat()`, que DESCARTA os rótulos de seção, e
     * despejava quinze destinos numa grade sem hierarquia — com "Acertos" e
     * "Seus acertos" lado a lado, indistinguíveis. Era a queixa literal de quem
     * usa o app: "não dá para saber qual é qual".
     */
    await expect(gaveta.getByText('Pessoal', { exact: false })).toBeVisible();
    await expect(gaveta.getByText('Compartilhado', { exact: false })).toBeVisible();

    await context.close();
  });

  test('dá para trocar de espaço sem sair do celular', async ({ browser }) => {
    const { context, wsId } = await contaComDados(browser);
    const page = await context.newPage();

    // Um segundo espaço: com um só, o seletor não teria para onde ir.
    const criado = await context.request.post(`${API}/workspaces/`, {
      data: { name: 'Viagem Chile', base_currency: 'BRL' },
    });
    const outro = await criado.json();

    await page.goto(`/w/${wsId}/transactions`);
    await page.waitForLoadState('networkidle').catch(() => {});

    /*
     * O `WorkspaceSwitcher` morava só dentro da `Sidebar`, que é `hidden
     * md:flex`: no celular NÃO HAVIA como trocar de espaço, nem como saber em
     * qual deles se estava. Quem participa do próprio espaço e de mais um ficava
     * preso naquele em que o app abriu.
     */
    await page.getByRole('button', { name: /Meu espaço|Pessoal/ }).first().click();
    const seletor = page.getByRole('dialog');
    await expect(seletor).toBeVisible();
    await seletor.getByText('Viagem Chile').click();

    // Trocar de espaço PRESERVA a subrota (workspacePath): quem estava em
    // Lançamentos continua em Lançamentos, na casa nova.
    await expect(page).toHaveURL(new RegExp(`/w/${outro.id}/transactions`));

    // E a barra superior passa a anunciar o espaço novo.
    await expect(page.getByRole('button', { name: /Viagem Chile/ })).toBeVisible();

    await context.close();
  });

  test('a camada pessoal se anuncia como pessoal', async ({ browser }) => {
    const { context } = await contaComDados(browser);
    const page = await context.newPage();
    await page.goto('/me/cards');
    await page.waitForLoadState('networkidle').catch(() => {});

    // Em `/me/*` o seletor usa `useWorkspaceIdFromUrl` (o estrito): antes, o
    // fallback para o último espaço visitado fazia a interface marcar um espaço
    // como "atual" enquanto a pessoa olhava os próprios cartões.
    await expect(page.getByRole('button', { name: /Pessoal/ })).toBeVisible();

    await context.close();
  });
});
