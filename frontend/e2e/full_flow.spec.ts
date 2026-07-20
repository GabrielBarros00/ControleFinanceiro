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
    await expect(page.getByRole('heading', { name: /Bem-vindo,/ })).toBeVisible();
    await page.getByRole('button', { name: /Começar Setup/ }).click();
    await page.getByLabel('Salário / Renda Líquida').fill('5000,00');
    await page.getByRole('button', { name: 'Próximo Passo' }).click();
    // "Pular" dispara window.location.reload() — espera a navegação terminar
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'load' }),
      page.getByRole('button', { name: 'Pular esta etapa' }).click(),
    ]);
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible({ timeout: 15_000 });

    // 3. Cria transação pela Entrada Rápida
    await page.getByLabel('Título / Descrição').fill('E2E Test Tx');
    await page.getByLabel('Valor Total').fill('123,45');

    // Seleciona pagador e participante (aguarda membros carregarem nas opções)
    const payer = page.getByLabel('Quem pagou?');
    await expect(payer.locator('option', { hasText: 'Test User' })).toHaveCount(1, { timeout: 10_000 });
    await payer.selectOption({ label: 'Test User' });

    const participants = page.getByLabel('Participante');
    if (await participants.count() === 0) {
      await page.getByRole('button', { name: '+ Participante' }).click();
    }
    await participants.first().selectOption({ label: 'Test User' });

    await page.getByRole('button', { name: 'Salvar Despesa' }).click();

    await expect(page.getByText('Salvo com sucesso!')).toBeVisible({ timeout: 10_000 });

    // 4. A transação aparece no histórico
    await expect(page.getByText('E2E Test Tx').first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/123,45/).first()).toBeVisible();
  });
});
