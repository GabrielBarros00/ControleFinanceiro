import { test, expect } from '@playwright/test';

const API = 'http://localhost:8000/api/v1';

test.describe('Dashboard and Split Entry Form', () => {
  test('should display the dashboard and allow adding a participant', async ({ browser }) => {
    const ts = Date.now();
    const context = await browser.newContext();

    // Setup via API: registro + login (cookies ficam no context) + onboarding
    await context.request.post(`${API}/auth/register`, {
      data: { name: 'Dash User', email: `dash${ts}@e2e.com`, password: 'senha123' },
    });
    await context.request.post(`${API}/auth/login`, {
      data: { email: `dash${ts}@e2e.com`, password: 'senha123' },
    });
    const [ws] = await (await context.request.get(`${API}/workspaces/`)).json();
    await context.request.post(`${API}/auth/onboarding`, {
      data: { workspace_id: ws.id, salary: 4000 },
    });

    const page = await context.newPage();
    await page.goto('/');

    // Dashboard renderizado
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
    await expect(page.getByText('Nova Despesa', { exact: true })).toBeVisible();

    // Preenche o formulário básico
    await page.getByLabel('Título / Descrição').fill('Pizza com amigos');
    await page.getByLabel('Valor Total').fill('150,00');

    // Método de divisão "Valor Fixo"
    await page.getByText('Valor Fixo').click();

    // Adiciona participante: 1 linha inicial + 1 nova = 2 botões de remover
    await page.getByRole('button', { name: '+ Participante' }).click();
    await expect(page.getByRole('button', { name: 'Remover participante' })).toHaveCount(2);

    // Botão de submit presente
    await expect(page.getByRole('button', { name: 'Salvar Despesa' })).toBeVisible();

    await context.close();
  });
});
