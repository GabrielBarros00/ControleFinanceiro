import { test, expect } from '@playwright/test';

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
    await expect(page.getByRole('heading', { name: /Início|Visão global/ })).toBeVisible();
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
    for (const rotulo of ['Visão global', 'Lançamentos', 'Cartões', 'Mais']) {
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
