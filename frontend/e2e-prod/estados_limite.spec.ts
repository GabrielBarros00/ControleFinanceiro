import { test, expect } from '@playwright/test';
import { registerAndLogin, defaultWorkspace } from './helpers';

/*
 * Estados-limite que quebram tela, contra a stack de produção.
 *
 * A varredura de console cobre as rotas com um usuário RECÉM-CRIADO — todas as
 * telas vazias. Faltavam os dois extremos que de fato derrubam a experiência:
 *
 * 1. **Sem workspace nenhum.** É um estado alcançável (excluir a única casa), e
 *    era o argumento para tirar perfil/senha de dentro de `/w/:id/settings`. Se
 *    a camada pessoal também quebrar aqui, a pessoa fica sem saída pela UI.
 * 2. **Com dados de verdade.** Gráficos, listas e agregações só falham quando há
 *    o que desenhar: uma tela vazia não exercita `recharts`, nem a formatação de
 *    moeda, nem o detalhamento do caixa.
 */
const API = 'http://localhost:8890/api/v1';

function vigiar(page: import('@playwright/test').Page) {
  const erros: string[] = [];
  page.on('console', (m) => {
    if (m.type() === 'error') erros.push(`[console.error] ${m.text()}`);
  });
  page.on('pageerror', (e) => erros.push(`[pageerror] ${e.message}`));
  return erros;
}

const semRuido = (erros: string[]) =>
  erros.filter((e) => !/favicon|manifest\.json/i.test(e));

test.describe('Estados-limite (stack de produção)', () => {
  test('sem workspace nenhum, a camada pessoal continua utilizável', async ({ page }) => {
    test.setTimeout(90_000);
    const erros = vigiar(page);
    const email = `sem-ws-${Date.now()}@example.com`;
    await registerAndLogin(page.context(), { name: 'Sem Casa', email, password: 'senha123' });
    const ws = await defaultWorkspace(page.context());

    // Exclui a única casa: o estado que o ADR 0021 usa como argumento.
    const del = await page.context().request.delete(`${API}/workspaces/${ws.id}`);
    expect(del.status(), await del.text()).toBe(200);

    for (const rota of ['/overview', '/me/settings', '/me/reports', '/me/commitments', '/me/cards']) {
      await page.goto(rota, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(900);
      // A tela tem de RENDERIZAR — não pode ficar em branco nem cair no login.
      await expect(page, `${rota} devolveu ao login`).not.toHaveURL(/\/login/);
      await expect(page.locator('h1'), `${rota} não renderizou título`).toBeVisible();
    }
    expect(semRuido(erros), semRuido(erros).join('\n')).toEqual([]);
  });

  test('com dados de verdade, as telas novas desenham sem erro', async ({ page }) => {
    test.setTimeout(120_000);
    const erros = vigiar(page);
    const email = `com-dados-${Date.now()}@example.com`;
    await registerAndLogin(page.context(), { name: 'Com Dados', email, password: 'senha123' });
    const ws = await defaultWorkspace(page.context());
    const req = page.context().request;

    const me = await (await req.get(`${API}/auth/me`)).json();
    // Renda + despesas em três meses: é o mínimo para a série ter o que desenhar
    // (com um mês só, os gráficos caem no estado "sem dados suficientes").
    const hoje = new Date();
    for (let atras = 0; atras < 3; atras++) {
      const d = new Date(hoje.getFullYear(), hoje.getMonth() - atras, 10);
      const mes = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
      const renda = await req.post(`${API}/me/income`, {
        data: {
          title: 'Salário', amount: '9000.00',
          received_at: `${mes}-05T12:00:00`, currency: 'BRL',
        },
      });
      expect(renda.status(), await renda.text()).toBe(200);
      for (const n of [1, 2]) {
        const tx = await req.post(`${API}/workspaces/${ws.id}/transactions/`, {
          data: {
            title: `Mercado ${mes} ${n}`, total_amount: '250.00',
            transaction_date: `${mes}-10T12:00:00`, billing_month: mes,
            payers: [{ user_id: me.id, amount: '250.00' }],
            splits: [{ user_id: me.id, split_method: 'equal', input_value: '0' }],
          },
        });
        expect(tx.status(), await tx.text()).toBe(200);
      }
    }

    for (const rota of ['/overview', '/me/reports', '/reports', '/me/income']) {
      await page.goto(rota, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(1500);
      await expect(page.locator('h1')).toBeVisible();
    }

    // O caixa do mês corrente saiu da primeira tela (era cópia literal do topo
    // do Extrato) — a verificação foi para onde o número mora agora.
    await page.goto('/me/ledger', { waitUntil: 'domcontentloaded' });
    await expect(page.getByText('Saiu')).toBeVisible();
    await expect(page.getByText('Saldo do mês')).toBeVisible();

    // E a primeira tela responde as três perguntas dela.
    await page.goto('/overview', { waitUntil: 'domcontentloaded' });
    await expect(page.getByText('Seu dinheiro')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Precisa de você' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Este mês' })).toBeVisible();

    // A série pessoal desenhou de fato, em vez do estado vazio.
    await page.goto('/me/reports', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1500);
    await expect(page.getByText('Renda × consumo')).toBeVisible();
    // Asserção NEGATIVA com o texto errado passa sempre — e esta passava:
    // "Ainda não há meses suficientes para comparar." não existe em lugar
    // nenhum do app. O estado vazio de verdade é o do `EmptyState` abaixo, e a
    // conta com dados NÃO pode cair nele.
    await expect(page.getByText('Nenhum movimento no período')).toHaveCount(0);

    expect(semRuido(erros), semRuido(erros).join('\n')).toEqual([]);
  });
});
