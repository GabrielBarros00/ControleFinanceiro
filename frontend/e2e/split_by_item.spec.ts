import { test, expect, type Page } from '@playwright/test';

// Registro + onboarding até o dashboard (mesmo fluxo do full_flow.spec)
async function registerAndOnboard(page: Page, name: string, email: string) {
  await page.goto('/register');
  await page.getByLabel('Nome Completo').fill(name);
  await page.getByLabel('E-mail').fill(email);
  await page.getByLabel('Senha', { exact: true }).fill('password123');
  await page.getByLabel('Confirmar', { exact: true }).fill('password123');
  await page.getByRole('button', { name: 'Cadastrar', exact: true }).click();

  await expect(page).toHaveURL('http://localhost:5173/');
  await expect(page.getByRole('heading', { name: /Bem-vindo,/ })).toBeVisible();
  await page.getByRole('button', { name: /Começar Setup/ }).click();
  await page.getByLabel('Salário / Renda Líquida').fill('5000,00');
  await page.getByRole('button', { name: 'Próximo Passo' }).click();
  await Promise.all([
    page.waitForNavigation({ waitUntil: 'load' }),
    page.getByRole('button', { name: 'Pular esta etapa' }).click(),
  ]);
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible({ timeout: 15_000 });
}

test.describe('Divisão por item e edição completa', () => {
  test('cria despesa dividida por item (qtd × unitário) e mostra na edição', async ({ page }) => {
    const email = `item_e2e_${Date.now()}@example.com`;
    await registerAndOnboard(page, 'Item Tester', email);

    await page.getByLabel('Título / Descrição').fill('Churrasco E2E');
    await page.getByLabel('Valor Total').fill('90,00');
    await page.getByLabel('Forma de pagamento').selectOption('pix');

    // Alterna para divisão por item — abre o editor com um item semeado
    await page.getByRole('radio', { name: 'Por item' }).click();
    await expect(page.getByLabel('Título do item')).toBeVisible();

    // Item 1: Carne, total direto de R$ 60
    await page.getByLabel('Título do item').fill('Carne');
    await page.getByLabel('Total do item').fill('60,00');

    // Item 2: Cerveja, 3 × R$ 10 (total da linha derivado)
    await page.getByRole('button', { name: 'Item', exact: true }).click();
    await page.getByLabel('Título do item').nth(1).fill('Cerveja');
    await page.getByLabel('Quantidade').nth(1).fill('3');
    await page.getByLabel('Valor unitário').nth(1).fill('10,00');

    // Resumo fecha o total
    await expect(page.getByTestId('items-summary')).toContainText('Itens fecham');

    await page.getByRole('button', { name: 'Salvar Despesa' }).click();
    await expect(page.getByText('Salvo com sucesso!')).toBeVisible({ timeout: 10_000 });

    // Histórico: transação com forma de pagamento Pix
    const row = page.getByRole('row', { name: /Churrasco E2E/ });
    await expect(row).toBeVisible({ timeout: 10_000 });
    await expect(row.getByText('Pix')).toBeVisible();

    // Edição mostra os itens persistidos (tela de detalhe da divisão)
    await row.getByRole('button', { name: 'Editar transação' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByLabel('Título do item').first()).toHaveValue('Carne');
    await expect(dialog.getByLabel('Título do item').nth(1)).toHaveValue('Cerveja');
    await expect(dialog.getByLabel('Quantidade').nth(1)).toHaveValue('3');
  });

  test('edita despesa trocando a divisão de igual para valor fixo', async ({ page }) => {
    const email = `edit_e2e_${Date.now()}@example.com`;
    await registerAndOnboard(page, 'Edit Tester', email);

    await page.getByLabel('Título / Descrição').fill('Edicao Full E2E');
    await page.getByLabel('Valor Total').fill('100,00');
    await page.getByRole('button', { name: 'Salvar Despesa' }).click();
    await expect(page.getByText('Salvo com sucesso!')).toBeVisible({ timeout: 10_000 });

    const row = page.getByRole('row', { name: /Edicao Full E2E/ });
    await expect(row).toBeVisible({ timeout: 10_000 });
    await row.getByRole('button', { name: 'Editar transação' }).click();

    const dialog = page.getByRole('dialog');
    await dialog.getByRole('radio', { name: 'Valor Fixo' }).click();
    await dialog.getByRole('textbox', { name: 'Valor fixo' }).fill('100,00');
    await expect(dialog.getByTestId('split-summary')).toContainText('Valores fecham');

    await dialog.getByRole('button', { name: 'Salvar Alterações' }).click();
    await expect(dialog).not.toBeVisible({ timeout: 10_000 });

    // Reabre e confere que o método persistiu
    await row.getByRole('button', { name: 'Editar transação' }).click();
    await expect(page.getByRole('dialog').getByRole('radio', { name: 'Valor Fixo' }))
      .toHaveAttribute('aria-checked', 'true');
  });
});
