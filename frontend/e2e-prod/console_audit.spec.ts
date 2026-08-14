import { test, expect } from '@playwright/test';
import { registerAndLogin, defaultWorkspace } from './helpers';

// Varredura de saúde do console: percorre todas as rotas protegidas atrás do
// nginx e falha se qualquer página emitir erro de console ou pageerror.
// Não usa networkidle: o app mantém um WebSocket aberto, então a rede nunca
// fica "idle". Espera domcontentloaded + um respiro para as queries assentarem.
// As rotas PESSOAIS entram pelo caminho novo (`/me/...`), não só pelas antigas
// que redirecionam: `/me/reports` e `/me/settings` nasceram na Onda 6 e não
// tinham nenhuma varredura — e são justamente as duas telas novas, uma delas
// com gráficos (recharts) e a outra com formulários. `/me/commitments` e
// `/overview` também nunca passaram por aqui.
const ROUTES = [
  // Pessoais
  '/', '/overview', '/me/income', '/me/cards', '/me/financing',
  '/me/commitments', '/me/reports', '/me/settings', '/me/settlements',
  // Do workspace (as antigas redirecionam para a última casa aberta)
  '/reports', '/recurring', '/debts', '/import', '/settings',
];

test.describe('Varredura de console (stack de produção)', () => {
  test('nenhuma rota protegida emite erro de console', async ({ page }) => {
    test.setTimeout(90_000);
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(`[console.error] ${msg.text()}`);
    });
    page.on('pageerror', (err) => errors.push(`[pageerror] ${err.message}`));

    const email = `console-${Date.now()}@example.com`;
    await registerAndLogin(page.context(), { name: 'Console Audit', email, password: 'senha123' });
    await defaultWorkspace(page.context());

    for (const route of ROUTES) {
      await page.goto(route, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(1200);
    }

    // Falhas de recurso estático não são erro de app.
    const appErrors = errors.filter((e) => !/favicon|manifest\.json/i.test(e));
    expect(appErrors, `Erros de console encontrados:\n${appErrors.join('\n')}`).toEqual([]);
  });
});
