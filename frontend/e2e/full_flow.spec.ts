import { test, expect } from '@playwright/test';

test.describe('Full User Flow', () => {
  const timestamp = Date.now();
  const email = `testuser_${timestamp}@example.com`;
  const password = 'password123';

  test('should register, onboard, and create a transaction', async ({ page }) => {
    // 1. Registro (auto-login e redirect para o dashboard)
    await page.goto('/register');
    await page.getByLabel('Nome Completo').fill('Test User');
    await page.getByLabel('E-mail').fill(email);
    await page.getByLabel('Senha', { exact: true }).fill(password);
    await page.getByLabel('Confirmar', { exact: true }).fill(password);
    await page.getByRole('button', { name: 'Cadastrar', exact: true }).click();

    await expect(page).toHaveURL('http://localhost:5173/');

    // 2. Onboarding (modal de boas-vindas em 3 passos)
    await expect(page.getByRole('heading', { name: 'Início' })).toBeVisible();
    await page.getByRole('button', { name: /Começar Setup/ }).click();
    await page.getByLabel('Salário / Renda Líquida').fill('5000,00');
    await page.getByRole('button', { name: 'Próximo Passo' }).click();
    // "Pular" dispara window.location.reload() — espera a navegação terminar
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'load' }),
      page.getByRole('button', { name: 'Pular esta etapa' }).click(),
    ]);
    await expect(page.getByRole('heading', { name: 'Início' })).toBeVisible({ timeout: 15_000 });

    // 3. Cria transação pelo modal Nova Despesa
    await page.locator('header').getByRole('button', { name: 'Nova despesa' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();

    await dialog.getByLabel('Título / Descrição').fill('E2E Test Tx');
    await dialog.getByLabel('Valor Total').fill('123,45');

    // Pagador e divisão usam os padrões (você paga e divide consigo mesmo)
    await dialog.getByRole('button', { name: 'Salvar Despesa' }).click();

    // Modal fecha ao salvar; toast confirma
    await expect(dialog).not.toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('Despesa adicionada')).toBeVisible({ timeout: 10_000 });

    // 4. A transação aparece no histórico
    await expect(page.getByText('E2E Test Tx').first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/123,45/).first()).toBeVisible();
  });
});
