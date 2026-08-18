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

  // Dado com TEXTO LONGO e VALOR ALTO de propósito: uma tela vazia cabe em
  // qualquer largura, e foi assim que o problema passou despercebido. O que
  // estoura é o título que não quebra e o número que não encolhe.
  await api.post(`${API}/me/income`, {
    data: {
      title: 'Salário — Consultoria Internacional de Tecnologia Ltda.',
      amount: '187450.90',
      received_at: new Date().toISOString(),
    },
  });
  await api.post(`${API}/workspaces/${ws.id}/transactions/`, {
    data: {
      title: 'Matrícula e mensalidade anual da escola bilíngue das crianças',
      total_amount: '94800.00',
      transaction_date: new Date().toISOString(),
      payment_method: 'pix',
    },
  });
  return { context, wsId: ws.id as number };
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

    const culpados: string[] = [];
    if (excesso > 1) {
      for (const el of Array.from(document.querySelectorAll<HTMLElement>('body *'))) {
        const r = el.getBoundingClientRect();
        if (r.width === 0) continue;
        if (r.right <= largura + 1) continue;

        /*
         * Ignora quem está DENTRO de um container de rolagem horizontal.
         *
         * Uma aba fora de vista dentro de uma faixa `overflow-x-auto` é o
         * comportamento pretendido, não um defeito — ela é recortada pelo
         * container e não empurra a página. Sem este filtro, cada faixa de abas
         * despejava seus cinco filhos na lista e o culpado real ficava de fora
         * do limite de seis.
         */
        let dentroDeRolagem = false;
        for (let p = el.parentElement; p && p !== doc; p = p.parentElement) {
          const overflow = getComputedStyle(p).overflowX;
          if (overflow === 'auto' || overflow === 'scroll' || overflow === 'hidden') {
            dentroDeRolagem = true;
            break;
          }
        }
        if (dentroDeRolagem) continue;

        const classe = typeof el.className === 'string' ? el.className.slice(0, 90) : '';
        culpados.push(`<${el.tagName.toLowerCase()} class="${classe}"> direita=${Math.round(r.right)}`);
        if (culpados.length >= 6) break;
      }
    }
    return { excesso, culpados, largura, innerWidth: window.innerWidth };
  });

  expect(
    diagnostico.excesso,
    `${rota} rola ${diagnostico.excesso}px na horizontal.\n`
      + `Viewport de layout: ${diagnostico.largura}px (window.innerWidth: ${diagnostico.innerWidth}px).\n`
      + `Prováveis culpados:\n  ${diagnostico.culpados.join('\n  ')}`,
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
