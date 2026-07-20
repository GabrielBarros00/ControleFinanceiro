import { test, expect, Page } from '@playwright/test';

// Regressão do bug: registro/login atrás do nginx (porta != 80) não redirecionava
// ao dashboard e qualquer rota protegida devolvia ao /login mesmo com cookie válido
// (307 de barra final com Location sem porta → clearStore no use-auth).

const PAGES: Array<[string, string]> = [
  ['/income', 'Rendas'],
  ['/cards', 'Cartões de Crédito'],
  ['/financing', 'Financiamentos'],
  ['/reports', 'Relatórios'],
  ['/recurring', 'Recorrência'],
  ['/debts', 'Dívidas'],
  ['/import', 'Importar'],
  ['/settings', 'Configurações'],
];

async function expectNotBouncedToLogin(page: Page, path: string) {
  await page.goto(path);
  // O bounce acontece após a query de /auth/me; espera a rede assentar
  await page.waitForLoadState('networkidle');
  await expect(page, `rota ${path} devolveu ao /login`).not.toHaveURL(/\/login/);
}

test.describe('Sessão atrás do nginx (stack de produção)', () => {
  const ts = Date.now();
  const email = `e2e_prod_${ts}@teste.com`;
  const password = 'senha123';

  test('registro → dashboard → F5 e navegação mantêm a sessão → logout', async ({ page }) => {
    // 1. Registro com auto-login deve cair no dashboard, não voltar ao /login
    await page.goto('/register');
    await page.getByLabel('Nome Completo').fill('Usuária E2E Prod');
    await page.getByLabel('E-mail').fill(email);
    await page.getByLabel('Senha', { exact: true }).fill(password);
    await page.getByLabel('Confirmar', { exact: true }).fill(password);
    await page.getByRole('button', { name: 'Cadastrar', exact: true }).click();

    await expect(page).toHaveURL(/\/$/, { timeout: 15_000 });
    await expect(page.getByRole('heading', { name: /Bem-vindo,/ })).toBeVisible({ timeout: 15_000 });

    // 2. Onboarding mínimo (salário + pular cartão; "Pular" recarrega a página)
    await page.getByRole('button', { name: /Começar Setup/ }).click();
    await page.getByLabel('Salário / Renda Líquida').fill('5000,00');
    await page.getByRole('button', { name: 'Próximo Passo' }).click();
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'load' }),
      page.getByRole('button', { name: 'Pular esta etapa' }).click(),
    ]);
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible({ timeout: 15_000 });

    // 3. F5 mantém a sessão (era o sintoma: reload devolvia ao /login)
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible({ timeout: 15_000 });
    await expect(page).not.toHaveURL(/\/login/);

    // 4. Todas as rotas protegidas abrem sem bounce
    for (const [path, title] of PAGES) {
      await expectNotBouncedToLogin(page, path);
      // Escopado ao header do Layout: páginas podem repetir o título em h2
      await expect(page.locator('header').getByRole('heading', { name: title })).toBeVisible({ timeout: 15_000 });
    }

    // 5. Logout devolve ao /login e rota protegida volta a exigir sessão
    await page.goto('/settings');
    await page.getByRole('button', { name: /Sair da Conta/ }).click();
    await expect(page).toHaveURL(/\/login/, { timeout: 15_000 });
    await page.goto('/');
    await expect(page).toHaveURL(/\/login/, { timeout: 15_000 });
  });

  test('login manual redireciona ao dashboard', async ({ page }) => {
    // Autossuficiente: worker pode reiniciar entre testes (ts é reavaliado),
    // então cria a própria conta via API antes do login pela UI
    const email2 = `e2e_prod_login_${Date.now()}@teste.com`;
    const res = await page.request.post('/api/v1/auth/register', {
      data: { name: 'Login E2E Prod', email: email2, password },
    });
    if (!res.ok()) throw new Error(`registro via API falhou: ${res.status()}`);

    await page.goto('/login');
    await page.getByLabel('E-mail').fill(email2);
    await page.getByLabel('Senha', { exact: true }).fill(password);
    await page.getByRole('button', { name: /Acessar Conta/ }).click();

    await expect(page).toHaveURL(/\/$/, { timeout: 15_000 });
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible({ timeout: 15_000 });
  });
});
