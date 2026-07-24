import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';

/**
 * NÃO é um teste de verdade — é um roteiro de captura de telas para o estudo de
 * redesign do frontend. Semeia dados realistas via API (APIRequestContext não
 * envia header Origin, então passa pelo middleware CSRF) e navega por todas as
 * rotas capturando screenshots em tema claro e escuro.
 *
 * Rodar isolado:  npx playwright test zz_screenshots.spec.ts
 * Saída:          frontend/screenshots/*.png
 */

// baseURL sem path: paths absolutos (/api/v1/...) resolvem certo no new URL().
const HOST = 'http://localhost:8000';
const u = (p: string) => `${HOST}/api/v1${p}`;
const SHOTS = path.join(process.cwd(), 'screenshots');
const ts = Date.now();
const email = `demo_${ts}@cf4.app`;
const password = 'password123';
const name = 'Ana Martins';

function iso(daysAgo: number): string {
  const d = new Date();
  d.setDate(d.getDate() - daysAgo);
  d.setHours(12, 0, 0, 0);
  return d.toISOString();
}

// Rotas autenticadas do app (title do Layout como âncora de "carregou")
const APP_ROUTES: Array<{ path: string; slug: string }> = [
  { path: '/', slug: 'dashboard' },
  { path: '/transactions', slug: 'lancamentos' },
  { path: '/income', slug: 'rendas' },
  { path: '/cards', slug: 'cartoes' },
  { path: '/financing', slug: 'financiamentos' },
  { path: '/reports', slug: 'relatorios' },
  { path: '/recurring', slug: 'recorrencia' },
  { path: '/debts', slug: 'dividas' },
  { path: '/import', slug: 'importar' },
  { path: '/settings', slug: 'configuracoes' },
];

test('seed data and capture all screens', async ({ page, playwright }) => {
  test.setTimeout(300_000);
  fs.mkdirSync(SHOTS, { recursive: true });

  // ------------------------------------------------------------------ SEED
  const api = await playwright.request.newContext();

  const reg = await api.post(u('/auth/register'), { data: { name, email, password } });
  expect(reg.ok(), `register: ${await reg.text()}`).toBeTruthy();
  const user = await reg.json();
  const uid: number = user.id;

  const login = await api.post(u('/auth/login'), { data: { email, password } });
  expect(login.ok(), `login: ${await login.text()}`).toBeTruthy();

  const wss = await (await api.get(u('/workspaces/'))).json();
  const wsId: number = wss[0].id;

  const cats: { id: number; name: string }[] = await (await api.get(u(`/workspaces/${wsId}/categories`))).json();
  const catId = (n: string): number | undefined => cats.find((c) => c.name === n)?.id;

  // Rendas
  await api.post(u(`/workspaces/${wsId}/income/`), { data: { title: 'Salário', amount: 7200, received_at: iso(20) } });
  await api.post(u(`/workspaces/${wsId}/income/`), { data: { title: 'Freelance Design', amount: 1850, received_at: iso(8) } });

  // Despesas (bulk) — títulos e valores realistas, espalhados no mês
  const txs = [
    { title: 'Supermercado Pão de Açúcar', total_amount: 435.9, transaction_date: iso(2), cat: 'Mercado' },
    { title: 'Aluguel Apartamento', total_amount: 2100, transaction_date: iso(18), cat: 'Moradia' },
    { title: 'Conta de Luz', total_amount: 187.42, transaction_date: iso(15), cat: 'Moradia' },
    { title: 'Uber para o trabalho', total_amount: 32.8, transaction_date: iso(1), cat: 'Transporte' },
    { title: 'Farmácia Drogasil', total_amount: 76.3, transaction_date: iso(6), cat: 'Saúde' },
    { title: 'Cinema Iguatemi', total_amount: 90, transaction_date: iso(4), cat: 'Lazer' },
    { title: 'Curso de Inglês', total_amount: 320, transaction_date: iso(12), cat: 'Educação' },
    { title: 'Netflix', total_amount: 55.9, transaction_date: iso(10), cat: 'Assinaturas' },
    { title: 'Spotify', total_amount: 21.9, transaction_date: iso(10), cat: 'Assinaturas' },
    { title: 'Restaurante Japonês', total_amount: 148.5, transaction_date: iso(3), cat: 'Alimentação' },
    { title: 'Padaria', total_amount: 28.4, transaction_date: iso(0), cat: 'Alimentação' },
    { title: 'Gasolina', total_amount: 250, transaction_date: iso(7), cat: 'Transporte' },
    { title: 'Presente Aniversário', total_amount: 120, transaction_date: iso(5), cat: 'Outros' },
  ];
  await api.post(u(`/workspaces/${wsId}/transactions/bulk`), {
    data: txs.map((t) => ({ title: t.title, total_amount: t.total_amount, transaction_date: t.transaction_date })),
  });

  // Atribui categoria (item único) a cada despesa recém-criada
  const list = await (await api.get(u(`/workspaces/${wsId}/transactions/?limit=100&page=1`))).json();
  for (const item of list.items) {
    const seed = txs.find((t) => t.title === item.title);
    const cid = seed?.cat ? catId(seed.cat) : undefined;
    if (cid) {
      await api.put(u(`/workspaces/${wsId}/transactions/${item.id}`), { data: { category_id: cid } });
    }
  }

  // Cartão de crédito + lançamentos na fatura (create completo com payer/split)
  const card = await (
    await api.post(u(`/workspaces/${wsId}/credit-cards/`), {
      data: { name: 'Nubank Ultravioleta', limit: 12000, closing_day: 28, due_day: 7 },
    })
  ).json();
  const charges = [
    { title: 'iFood', amount: 68.5 },
    { title: 'Amazon.com.br', amount: 239.9 },
    { title: 'Posto Shell', amount: 300 },
    { title: 'Zara', amount: 419.9 },
  ];
  for (const c of charges) {
    await api.post(u(`/workspaces/${wsId}/transactions/`), {
      data: {
        title: c.title,
        total_amount: c.amount,
        transaction_date: iso(3),
        payment_method: 'credit_card',
        credit_card_id: card.id,
        split_mode: 'transaction',
        payers: [{ user_id: uid, amount: c.amount }],
        splits: [{ user_id: uid, split_method: 'equal', input_value: 100 }],
      },
    });
  }

  // ----------------------------------------------------------- SCREENSHOTS
  await page.setViewportSize({ width: 1440, height: 900 });

  // Sempre injeta o workspace atual (persist do zustand) antes do app carregar.
  // NÃO mexe no theme aqui — o theme é controlado por evaluate+reload por fase.
  await page.addInitScript((ws) => {
    localStorage.setItem('cf4-ui', JSON.stringify({ state: { currentWorkspaceId: ws }, version: 0 }));
  }, wsId);

  const shot = async (slug: string) => {
    await page.screenshot({ path: path.join(SHOTS, `${slug}.png`), fullPage: true });
  };

  const settle = async () => {
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.waitForTimeout(900); // deixa as animações fade-in/framer terminarem
  };

  // ---- Público (tema claro) ----
  await page.goto('/login');
  await settle();
  await shot('auth-login');

  await page.goto('/register');
  await settle();
  await shot('auth-register');

  await page.goto('/forgot-password');
  await settle();
  await shot('auth-forgot-password');

  // ---- Login pela UI (garante cookie no contexto do browser) ----
  await page.goto('/login');
  await page.getByLabel('E-mail').fill(email);
  await page.getByLabel('Senha', { exact: true }).fill(password);
  await page.getByRole('button', { name: /Acessar Conta/ }).first().click();
  await page.waitForURL('**/');
  await settle();

  // Onboarding aparece para needs_onboarding=true
  await shot('onboarding-modal');

  // Encerra o onboarding via API (flip do flag, sem criar renda/cartão) e recarrega
  await api.post(u('/auth/onboarding'), { data: { workspace_id: wsId, salary: 0 } });

  const captureAll = async (theme: 'light' | 'dark') => {
    // aplica o theme e recarrega (addInitScript re-seta só o workspace)
    await page.goto('/');
    await page.evaluate((t) => localStorage.setItem('theme', t), theme);
    await page.reload();
    await settle();

    for (const r of APP_ROUTES) {
      await page.goto(r.path);
      await settle();
      await shot(`${r.slug}-${theme}`);
    }

    // Modal Nova Despesa (a partir do dashboard)
    await page.goto('/');
    await settle();
    const novaBtn = page.getByRole('button', { name: 'Nova Despesa' });
    if (await novaBtn.count()) {
      await novaBtn.first().click();
      await page.getByRole('dialog').waitFor({ state: 'visible' }).catch(() => {});
      await page.waitForTimeout(600);
      await shot(`nova-despesa-modal-${theme}`);
      await page.keyboard.press('Escape').catch(() => {});
    }

    // Modal Nova Renda — verifica o switch "Renda recorrente" (contraste OFF/ON)
    // e o campo "Começa em" do editor de recorrência.
    await page.goto('/income');
    await settle();
    const novaRenda = page.getByRole('button', { name: /Nova renda/i });
    if (await novaRenda.count()) {
      await novaRenda.first().click();
      await page.getByRole('dialog').waitFor({ state: 'visible' }).catch(() => {});
      await page.waitForTimeout(500);
      await shot(`nova-renda-modal-off-${theme}`);
      const sw = page.getByRole('switch');
      if (await sw.count()) {
        await sw.first().click();
        await page.waitForTimeout(500);
        await shot(`nova-renda-modal-on-${theme}`);
      }
      await page.keyboard.press('Escape').catch(() => {});
    }
  };

  await captureAll('light');
  await captureAll('dark');

  // ---- Mobile (bottom-nav + responsivo, tema claro) ----
  await page.goto('/');
  await page.evaluate(() => localStorage.setItem('theme', 'light'));
  await page.setViewportSize({ width: 390, height: 844 });
  for (const r of [
    { path: '/', slug: 'inicio' },
    { path: '/transactions', slug: 'lancamentos' },
    { path: '/reports', slug: 'relatorios' },
  ]) {
    await page.goto(r.path);
    await settle();
    await shot(`mobile-${r.slug}`);
  }

  console.log(`\n>>> Screenshots salvos em: ${SHOTS}\n`);
});
