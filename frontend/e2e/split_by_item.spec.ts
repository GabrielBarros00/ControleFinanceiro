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
  // O onboarding virou um Dialog de verdade: enquanto ele está aberto, o resto
  // da página fica inerte (aria-hidden) — o cabeçalho "Início" atrás dele deixa
  // de ser alcançável por role, que é justamente o comportamento correto.
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.getByRole('button', { name: /Começar Setup/ }).click();
  await page.getByLabel('Salário / Renda Líquida').fill('5000,00');
  await page.getByRole('button', { name: 'Próximo Passo' }).click();
  await Promise.all([
    page.waitForNavigation({ waitUntil: 'load' }),
    page.getByRole('button', { name: 'Pular esta etapa' }).click(),
  ]);
  await expect(page.getByRole('heading', { name: 'Início' })).toBeVisible({ timeout: 15_000 });
}

test.describe('Divisão por item e edição completa', () => {
  test('cria despesa dividida por item (qtd × unitário) e mostra na edição', async ({ page }) => {
    const email = `item_e2e_${Date.now()}@example.com`;
    await registerAndOnboard(page, 'Item Tester', email);

    // Abre o modal de Nova Despesa
    await page.locator('header').getByRole('button', { name: 'Nova despesa' }).click();
    const createDialog = page.getByRole('dialog');
    await expect(createDialog).toBeVisible();

    await createDialog.getByLabel('Título / Descrição').fill('Churrasco E2E');
    await createDialog.getByLabel('Valor Total').fill('90,00');
    await createDialog.getByLabel('Forma de pagamento').selectOption('pix');

    // Divisão por item mora em "Opções avançadas"
    await createDialog.getByRole('button', { name: /Opções avançadas/ }).click();
    await createDialog.getByRole('radio', { name: 'Por item' }).click();
    await expect(createDialog.getByLabel('Título do item')).toBeVisible();

    // Item 1: Carne, total direto de R$ 60
    await createDialog.getByLabel('Título do item').fill('Carne');
    await createDialog.getByLabel('Total do item').fill('60,00');

    // Item 2: Cerveja, 3 × R$ 10 (total da linha derivado)
    await createDialog.getByRole('button', { name: 'Item', exact: true }).click();
    await createDialog.getByLabel('Título do item').nth(1).fill('Cerveja');
    await createDialog.getByLabel('Quantidade').nth(1).fill('3');
    await createDialog.getByLabel('Valor unitário').nth(1).fill('10,00');

    // Resumo fecha o total
    await expect(createDialog.getByTestId('items-summary')).toContainText('Itens fecham');

    await createDialog.getByRole('button', { name: 'Salvar Despesa' }).click();
    await expect(createDialog).not.toBeVisible({ timeout: 10_000 });

    // Extrato: transação com forma de pagamento Pix. Editar/excluir só existem
    // em Lançamentos — no Início a linha abre o detalhe.
    await page.goto('/transactions');
    const row = page.getByTestId('ledger-row').filter({ hasText: 'Churrasco E2E' });
    await expect(row).toBeVisible({ timeout: 10_000 });
    await expect(row).toContainText('Pix');

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

    await page.locator('header').getByRole('button', { name: 'Nova despesa' }).click();
    const createDialog = page.getByRole('dialog');
    await expect(createDialog).toBeVisible();
    await createDialog.getByLabel('Título / Descrição').fill('Edicao Full E2E');
    await createDialog.getByLabel('Valor Total').fill('100,00');
    await createDialog.getByRole('button', { name: 'Salvar Despesa' }).click();
    await expect(createDialog).not.toBeVisible({ timeout: 10_000 });

    await page.goto('/transactions');
    const row = page.getByTestId('ledger-row').filter({ hasText: 'Edicao Full E2E' });
    await expect(row).toBeVisible({ timeout: 10_000 });
    await row.getByRole('button', { name: 'Editar transação' }).click();

    const dialog = page.getByRole('dialog');
    // A despesa criada é "igual" (simples) → abre as opções avançadas para trocar o método
    await dialog.getByRole('button', { name: /Opções avançadas/ }).click();
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
