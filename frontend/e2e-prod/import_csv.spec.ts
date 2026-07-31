import { test, expect } from '@playwright/test';
import { registerAndLogin, defaultWorkspace } from './helpers';

// Regressão do bug de import: o hook enviava { transactions: [...] } mas o
// endpoint bulk recebe a lista pura — a UI sempre falhava com 422.
test('importa CSV pela UI: parse, preview e confirmação', async ({ page, context }) => {
  test.setTimeout(120_000);
  const ts = Date.now();
  await registerAndLogin(context, { name: 'Import E2E', email: `import_${ts}@teste.com`, password: 'senha123' });
  const ws = await defaultWorkspace(context);

  await page.goto('/import');
  await expect(page.locator('header').getByRole('heading', { name: 'Importar' })).toBeVisible({ timeout: 15_000 });

  // CSV no formato default da página: ';' como delimitador, vírgula decimal, %d/%m/%Y
  const csv = 'Data;Descricao;Valor\n01/02/2026;Mercado E2E;-150,50\n02/02/2026;Padaria E2E;-12,30\n';
  await page.locator('input[type="file"]').setInputFiles({
    name: 'extrato.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(csv, 'utf-8'),
  });

  await page.getByRole('button', { name: 'Processar Arquivo' }).click();
  await expect(page.getByText('Mercado E2E')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText('Padaria E2E')).toBeVisible();

  await page.getByRole('button', { name: /Confirmar 2 Transações/ }).click();

  // Toast confirma a importação e a navegação volta ao dashboard
  await expect(page.getByText(/2 criada\(s\)/)).toBeVisible({ timeout: 15_000 });
  await expect(page).toHaveURL(/\/overview$/, { timeout: 15_000 });
  const list = await (await page.request.get(`/api/v1/workspaces/${ws.id}/transactions/`)).json();
  const titles = (list.items ?? list).map((t: { title: string }) => t.title);
  expect(titles).toContain('Mercado E2E');
  expect(titles).toContain('Padaria E2E');
});
