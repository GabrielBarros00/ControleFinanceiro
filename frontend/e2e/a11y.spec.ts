import AxeBuilder from '@axe-core/playwright';
import { test, expect, type Page } from '@playwright/test';

/*
 * F5.3 do roadmap de redesign — a auditoria de acessibilidade que nunca tinha
 * rodado. Cobre as telas que mais importam: a PRIMEIRA que um usuário novo vê
 * (onboarding), a que ele usa todo dia (Início), o formulário mais rico do app
 * (Nova Despesa) e a mais densa em cor/gráfico (Relatórios).
 *
 * Escopo: `wcag2a` + `wcag2aa` — as violações que são realmente defeito, não
 * preferência de estilo. Falha o teste, não avisa: um regressor de contraste ou
 * de rótulo passa despercebido em revisão de código.
 */
const API = 'http://localhost:8000/api/v1';
const PADRAO = ['wcag2a', 'wcag2aa'];

async function analisar(page: Page, seletor?: string) {
  let builder = new AxeBuilder({ page }).withTags(PADRAO);
  if (seletor) builder = builder.include(seletor);
  return builder.analyze();
}

/** Erro legível: o dump cru do axe não diz em qual elemento o problema está. */
function resumir(violations: Awaited<ReturnType<typeof analisar>>['violations']) {
  return violations
    .map((v) => `${v.id} (${v.impact}): ${v.help}\n    ${v.nodes.map((n) => n.target.join(' ')).join('\n    ')}`)
    .join('\n\n');
}

async function contaNova(browser: Parameters<Parameters<typeof test>[1]>[0]['browser']) {
  const ts = Date.now() + Math.floor(Math.random() * 1000);
  const email = `a11y${ts}@e2e.com`;
  const context = await browser.newContext();
  await context.request.post(`${API}/auth/register`, {
    data: { name: 'Ana Acessível', email, password: 'senha123' },
  });
  await context.request.post(`${API}/auth/login`, {
    data: { email, password: 'senha123' },
  });
  return context;
}

test.describe('Acessibilidade (axe · WCAG 2 A/AA)', () => {
  test('Onboarding — a primeira tela do usuário novo', async ({ browser }) => {
    const context = await contaNova(browser);
    const page = await context.newPage();
    await page.goto('/');

    // Sem concluir o onboarding, o modal bloqueante é o que está na tela
    const dialogo = page.getByRole('dialog');
    await expect(dialogo).toBeVisible();

    const { violations } = await analisar(page);
    expect(resumir(violations)).toBe('');
    await context.close();
  });

  test('Início e Nova Despesa', async ({ browser }) => {
    const context = await contaNova(browser);
    const [ws] = await (await context.request.get(`${API}/workspaces/`)).json();
    await context.request.post(`${API}/auth/onboarding`, { data: { salary: 4000 } });
    expect(ws.id).toBeTruthy();

    const page = await context.newPage();
    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'Início' })).toBeVisible();

    const inicio = await analisar(page);
    expect(resumir(inicio.violations)).toBe('');

    await page.locator('header').getByRole('button', { name: 'Nova despesa' }).click();
    await expect(page.getByRole('dialog')).toBeVisible();
    // Inclui as "Opções avançadas": é onde moram os campos de divisão
    await page.getByRole('dialog').getByRole('button', { name: /Opções avançadas/ }).click();

    const form = await analisar(page, '[role="dialog"]');
    expect(resumir(form.violations)).toBe('');
    await context.close();
  });

  test('Relatórios — a tela mais densa em cor', async ({ browser }) => {
    const context = await contaNova(browser);
    await context.request.post(`${API}/auth/onboarding`, { data: { salary: 4000 } });

    const page = await context.newPage();
    await page.goto('/reports');
    await expect(page.getByRole('heading', { name: /Relatórios/i })).toBeVisible();

    const { violations } = await analisar(page);
    expect(resumir(violations)).toBe('');
    await context.close();
  });
});
