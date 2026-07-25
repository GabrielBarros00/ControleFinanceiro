import { test, expect } from '@playwright/test';
import { registerAndLogin, defaultWorkspace } from './helpers';

// Auditoria da stack de produção (nginx + backend production):
// 1) WebSocket através do proxy nginx: mutação de A aparece para B sem reload
//    e B ressincroniza após ficar offline (gap no seq → resync).
// 2) Convite por link aceito pela UI (/invite/:token).
const API = '/api/v1';

test.describe('Stack de produção: tempo real e convite por link', () => {
  test('WS via nginx: mutação de A chega a B sem reload e resync após offline', async ({ browser }) => {
    test.setTimeout(120_000);
    const ts = Date.now();
    const contextA = await browser.newContext();
    const contextB = await browser.newContext();

    await registerAndLogin(contextA, { name: 'Alice RT', email: `rt_a_${ts}@teste.com`, password: 'senha123' });
    await registerAndLogin(contextB, { name: 'Bruno RT', email: `rt_b_${ts}@teste.com`, password: 'senha123' });

    const wsA = await defaultWorkspace(contextA);
    await defaultWorkspace(contextB);

    const sharedWsName = `Compartilhado ${ts}`;
    await contextA.request.put(`${API}/workspaces/${wsA.id}`, { data: { name: sharedWsName } });
    const invite = await contextA.request.post(`${API}/workspaces/${wsA.id}/invites`, {
      data: { email: `rt_b_${ts}@teste.com`, role: 'member' },
    });
    expect((await invite.json()).status).toBe('member_added');

    const pageA = await contextA.newPage();
    const pageB = await contextB.newPage();
    await pageA.goto('/');
    await expect(pageA.getByRole('heading', { name: 'Início' })).toBeVisible({ timeout: 15_000 });
    await pageB.goto('/');
    await expect(pageB.getByRole('heading', { name: 'Início' })).toBeVisible({ timeout: 15_000 });

    await pageB.getByRole('button', { name: /Workspace/i }).click();
    await pageB.getByRole('button', { name: sharedWsName }).click();
    await expect(pageB.getByRole('button', { name: new RegExp(sharedWsName) })).toBeVisible();

    const meA = await (await contextA.request.get(`${API}/auth/me`)).json();
    const createTxAs = (title: string) =>
      contextA.request.post(`${API}/workspaces/${wsA.id}/transactions/`, {
        data: {
          title,
          total_amount: '90.00',
          transaction_date: new Date().toISOString(),
          payers: [{ user_id: meA.id, amount: '90.00' }],
          splits: [{ user_id: meA.id, split_method: 'equal', input_value: '100' }],
        },
      });

    const titleLive = `Jantar Tempo Real ${ts}`;
    expect((await createTxAs(titleLive)).ok()).toBeTruthy();
    await expect(pageB.getByText(titleLive)).toBeVisible({ timeout: 15_000 });

    await contextB.setOffline(true);
    const titleOffline = `Offline ${ts}`;
    expect((await createTxAs(titleOffline)).ok()).toBeTruthy();
    await expect(pageB.getByText(titleOffline)).not.toBeVisible();

    await contextB.setOffline(false);
    await expect(pageB.getByText(titleOffline)).toBeVisible({ timeout: 30_000 });

    await contextA.close();
    await contextB.close();
  });

  test('convite por link: usuário novo aceita pela UI e entra no workspace', async ({ browser }) => {
    test.setTimeout(120_000);
    const ts = Date.now();
    const contextA = await browser.newContext();
    const contextC = await browser.newContext();

    await registerAndLogin(contextA, { name: 'Alice Link', email: `link_a_${ts}@teste.com`, password: 'senha123' });
    const wsA = await defaultWorkspace(contextA);
    const linkWsName = `Via Link ${ts}`;
    await contextA.request.put(`${API}/workspaces/${wsA.id}`, { data: { name: linkWsName } });

    const linkRes = await contextA.request.post(`${API}/workspaces/${wsA.id}/invites/link`, {
      data: { role: 'member', expires_days: 7 },
    });
    expect(linkRes.ok()).toBeTruthy();
    const { token } = await linkRes.json();
    expect(token).toBeTruthy();

    await registerAndLogin(contextC, { name: 'Carla Link', email: `link_c_${ts}@teste.com`, password: 'senha123' });
    await defaultWorkspace(contextC);

    const pageC = await contextC.newPage();
    await pageC.goto(`/invite/${token}`);
    await pageC.getByRole('button', { name: 'Aceitar Convite' }).click();

    // Depois de aceitar, o workspace convidado aparece para Carla
    await pageC.goto('/');
    await expect(pageC.getByRole('heading', { name: 'Início' })).toBeVisible({ timeout: 15_000 });
    const wsListC = await (await contextC.request.get(`${API}/workspaces/`)).json();
    expect(wsListC.some((w: { name: string }) => w.name === linkWsName)).toBeTruthy();

    await contextA.close();
    await contextC.close();
  });
});
