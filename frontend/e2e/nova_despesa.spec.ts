import { test, expect, type Page, type Browser } from '@playwright/test';
import { diaLocal } from '../e2e-shared/datas';

/**
 * O formulário mais usado do app — medido pelo que ele obriga a LER.
 *
 * ## A métrica errada, e por que ela foi trocada
 *
 * O primeiro portão escrito aqui media toques: "lançar uma despesa em até 4
 * toques". Ao medir, o app **já fazia em 4 toques e sem rolagem** — o rodapé
 * fixo de uma rodada anterior tinha resolvido o que faltava. O portão teria
 * nascido verde, o que é o mesmo que não existir.
 *
 * O problema da tela nunca foi mecânico. Para lançar um café de R$ 12,50, o
 * formulário abre com **catorze controles visíveis** e nove rótulos — pagador,
 * data, forma de pagamento, "já foi paga", etiquetas, divisão, "opções
 * avançadas" — para preencher **dois campos**. Nenhum deles está errado; todos
 * têm um padrão razoável; e ainda assim é tudo isso que a pessoa varre com o
 * olho, dez vezes por dia, antes de achar "Título" e "Valor".
 *
 * Por isso a régua é **quantidade de controles à vista no modo simples**. Ela
 * mede o custo de leitura, que é o custo real.
 *
 * ## O que conta como controle
 *
 * Qualquer coisa que peça uma decisão: `input`, `select`, `textarea`, e botão
 * que não seja a ação principal. Não contam: o botão de salvar, o de fechar do
 * diálogo, e o próprio "Detalhar" — eles são a saída, não a pergunta.
 */
const API = 'http://localhost:8000/api/v1';

/** O teto: título, valor, e sobra para três. Hoje são 14. */
const MAXIMO_DE_CONTROLES = 5;

async function contaComEspaco(browser: Browser) {
  const ts = Date.now() + Math.floor(Math.random() * 1000);
  const email = `despesa${ts}@e2e.com`;
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const api = context.request;

  await api.post(`${API}/auth/register`, { data: { name: 'Rita Lança', email, password: 'senha123' } });
  await api.post(`${API}/auth/login`, { data: { email, password: 'senha123' } });
  await api.post(`${API}/auth/onboarding`, { data: { salary: 5000 } });
  const [ws] = await (await api.get(`${API}/workspaces/`)).json();
  return { context, wsId: ws.id as number };
}

/** Os controles que o diálogo mostra AGORA — só os que estão de fato visíveis. */
async function controlesVisiveis(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const dialogo = document.querySelector('[role="dialog"]');
    if (!dialogo) return [];
    const saidas = /^(salvar|cancelar|fechar|detalhar|salvar despesa|salvar e lançar outro)$/i;
    const achados: string[] = [];
    for (const el of Array.from(
      dialogo.querySelectorAll<HTMLElement>('input, select, textarea, button, [role="combobox"], [role="switch"]'),
    )) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      if (getComputedStyle(el).visibility === 'hidden') continue;
      const nome = (
        el.getAttribute('aria-label')
        || el.textContent?.trim()
        || (el as HTMLInputElement).placeholder
        || el.id
        || el.tagName
      ).slice(0, 40);
      if (el.tagName === 'BUTTON' && saidas.test(nome)) continue;
      achados.push(nome);
    }
    return achados;
  });
}

async function abrirNovaDespesa(page: Page, wsId: number) {
  await page.goto(`/w/${wsId}`);
  await page.locator('header').getByRole('button', { name: 'Nova despesa' }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
}

test('o formulário simples não pede mais do que precisa', async ({ browser }) => {
  const { context, wsId } = await contaComEspaco(browser);
  const page = await context.newPage();
  await abrirNovaDespesa(page, wsId);

  const controles = await controlesVisiveis(page);

  await context.close();
  expect(
    controles.length,
    `O formulário abre com ${controles.length} controles para preencher dois campos:\n  `
    + controles.join('\n  '),
  ).toBeLessThanOrEqual(MAXIMO_DE_CONTROLES);
});

test('"Detalhar" traz o formulário inteiro sem perder o que foi digitado', async ({ browser }) => {
  const { context, wsId } = await contaComEspaco(browser);
  const page = await context.newPage();
  await abrirNovaDespesa(page, wsId);

  const dialogo = page.getByRole('dialog');
  await dialogo.getByLabel('Título / Descrição').fill('Café');
  await dialogo.getByLabel('Valor Total').fill('12,50');

  await dialogo.getByRole('button', { name: /detalhar/i }).click();

  // O que foi digitado continua lá: esconder campos não pode custar o trabalho
  // já feito, senão ninguém arrisca clicar.
  await expect(dialogo.getByLabel('Título / Descrição')).toHaveValue('Café');
  await expect(dialogo.getByLabel('Valor Total')).toHaveValue('12,50');
  // E o resto do formulário aparece.
  await expect(dialogo.getByLabel('Data', { exact: true })).toBeVisible();

  const controles = await controlesVisiveis(page);
  expect(
    controles.length,
    'detalhar tem de abrir MAIS do que o simples — senão ele não abriu nada',
  ).toBeGreaterThan(MAXIMO_DE_CONTROLES);

  await context.close();
});

test('lançar dois cafés seguidos sem reabrir o formulário', async ({ browser }) => {
  const { context, wsId } = await contaComEspaco(browser);
  const page = await context.newPage();
  await abrirNovaDespesa(page, wsId);

  const dialogo = page.getByRole('dialog');
  await dialogo.getByLabel('Título / Descrição').fill('Café');
  await dialogo.getByLabel('Valor Total').fill('12,50');
  await dialogo.getByRole('button', { name: /salvar e lançar outro/i }).click();

  // O diálogo FICA, limpo e com o foco no título: quem lança três compras
  // seguidas não deveria reabrir o modal três vezes.
  await expect(dialogo).toBeVisible();
  await expect(dialogo.getByLabel('Título / Descrição')).toHaveValue('');
  await expect(dialogo.getByLabel('Título / Descrição')).toBeFocused();

  await dialogo.getByLabel('Título / Descrição').fill('Pão');
  await dialogo.getByLabel('Valor Total').fill('8,00');
  await dialogo.getByRole('button', { name: 'Salvar despesa' }).click();
  await expect(dialogo).toBeHidden();

  await page.goto(`/w/${wsId}/transactions`);
  await expect(page.getByText('Café')).toBeVisible();
  await expect(page.getByText('Pão')).toBeVisible();

  await context.close();
});

test('duplicar repete o lançamento sem herdar a data do original', async ({ browser }) => {
  const { context, wsId } = await contaComEspaco(browser);
  const page = await context.newPage();

  // Uma despesa de ONTEM: se a duplicata herdasse a data, ela nasceria no
  // passado sem ninguém pedir — e num fim de mês, no mês errado.
  const ontem = diaLocal(-1);
  await abrirNovaDespesa(page, wsId);
  const dialogo = page.getByRole('dialog');
  await dialogo.getByLabel('Título / Descrição').fill('Mercado da semana');
  await dialogo.getByLabel('Valor Total').fill('220,00');
  await dialogo.getByRole('button', { name: /^Detalhar$/ }).click();
  await dialogo.getByLabel('Data', { exact: true }).fill(ontem);
  await dialogo.getByRole('button', { name: 'Salvar despesa' }).click();
  await expect(dialogo).toBeHidden();

  await page.goto(`/w/${wsId}/transactions`);
  await page.getByText('Mercado da semana').first().click();

  const detalhe = page.getByRole('dialog');
  await detalhe.getByRole('button', { name: /duplicar/i }).click();

  const novo = page.getByRole('dialog');
  await expect(novo.getByLabel('Título / Descrição')).toHaveValue('Mercado da semana');
  await expect(novo.getByLabel('Valor Total')).toHaveValue('220,00');

  await novo.getByRole('button', { name: /^Detalhar$/ }).click();
  const hoje = diaLocal();
  await expect(novo.getByLabel('Data', { exact: true })).toHaveValue(hoje);

  await context.close();
});
