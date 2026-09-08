import { test, expect } from '@playwright/test';
import { ONBOARDING } from '../e2e-shared/rotulos';

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

    // `/` leva ao Início GLOBAL (ADR 0020): a tela pessoal que soma todos os
    // workspaces. Criar despesa é ato de UM workspace, então o fluxo entra
    // num deles logo abaixo.
    await expect(page).toHaveURL(/\/overview$/);

    // 2. Onboarding (modal de boas-vindas em 3 passos). É um Dialog: enquanto
    // aberto, o resto da página fica inerte e o "Início" atrás dele não é
    // alcançável por role — comportamento correto, e o que esperamos aqui.
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.getByRole('button', { name: ONBOARDING.comecar }).click();
    // O onboarding virou um passo: onde está o dinheiro e quanto há nele.
    await page.getByLabel(ONBOARDING.ondeEstaODinheiro).fill('Nubank');
    await page.getByLabel(ONBOARDING.quantoHa).fill('5000,00');
    // "Pular" dispara window.location.reload() — espera a navegação terminar
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'load' }),
      page.getByRole('button', { name: ONBOARDING.concluir }).click(),
    ]);
    await expect(page.getByRole('heading', { name: /Hoje|Painel/ })).toBeVisible({ timeout: 15_000 });

    // Entra no workspace: o painel da casa é onde se lança despesa.
    await page.getByRole('link', { name: 'Painel' }).click();
    await expect(page).toHaveURL(/\/w\/\d+$/);

    // 3. Cria transação pelo modal Nova Despesa
    await page.locator('header').getByRole('button', { name: 'Nova despesa' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();

    await dialog.getByLabel('Título / Descrição').fill('E2E Test Tx');
    await dialog.getByLabel('Valor Total').fill('123,45');

    // Pagador e divisão usam os padrões (você paga e divide consigo mesmo)
    await dialog.getByRole('button', { name: 'Salvar despesa' }).click();

    // Modal fecha ao salvar; toast confirma
    await expect(dialog).not.toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('Despesa adicionada')).toBeVisible({ timeout: 10_000 });

    // 4. A transação aparece no histórico
    await expect(page.getByText('E2E Test Tx').first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/123,45/).first()).toBeVisible();
  });
});
