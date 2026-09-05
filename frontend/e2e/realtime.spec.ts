import { test, expect, type BrowserContext } from '@playwright/test';

const API = 'http://localhost:8000/api/v1';

/**
 * E2E de tempo real: dois usuários no MESMO workspace veem as mutações um
 * do outro sem recarregar a página (WebSocket + invalidação), e o cliente
 * ressincroniza após ficar offline (gap no seq → resync completo).
 */
test.describe('Tempo real entre dois usuários', () => {
  const ts = Date.now();
  const userA = { name: 'Alice E2E', email: `alice${ts}@e2e.com`, password: 'senha123' };
  const userB = { name: 'Bruno E2E', email: `bruno${ts}@e2e.com`, password: 'senha123' };
  const sharedWsName = `Compartilhado ${ts}`;

  async function registerAndLogin(context: BrowserContext, user: typeof userA) {
    const reg = await context.request.post(`${API}/auth/register`, { data: user });
    expect(reg.ok()).toBeTruthy();
    const login = await context.request.post(`${API}/auth/login`, {
      data: { email: user.email, password: user.password },
    });
    expect(login.ok()).toBeTruthy();
  }

  async function getWorkspaces(context: BrowserContext) {
    const res = await context.request.get(`${API}/workspaces/`);
    return await res.json();
  }

  async function finishOnboarding(context: BrowserContext, workspaceId: number) {
    await context.request.post(`${API}/auth/onboarding`, {
      data: { workspace_id: workspaceId, salary: 5000 },
    });
  }

  test('mutação de A aparece para B sem reload; B ressincroniza após offline', async ({ browser }) => {
    test.setTimeout(120_000);

    const contextA = await browser.newContext();
    const contextB = await browser.newContext();

    // --- Setup via API (cookies ficam nos contexts) ---
    await registerAndLogin(contextA, userA);
    await registerAndLogin(contextB, userB);

    const [wsA] = await getWorkspaces(contextA);
    await finishOnboarding(contextA, wsA.id);
    const [wsB] = await getWorkspaces(contextB);
    await finishOnboarding(contextB, wsB.id);

    // A renomeia o próprio workspace e convida B. O convite NÃO adiciona
    // ninguém: desde o consentimento no convite (E15), quem já tem conta recebe
    // uma notificação e precisa ACEITAR — convidar não dá a si mesmo uma plateia
    // para as finanças alheias. O token do aceite chega pela notificação.
    await contextA.request.put(`${API}/workspaces/${wsA.id}`, { data: { name: sharedWsName } });
    const invite = await contextA.request.post(`${API}/workspaces/${wsA.id}/invites`, {
      data: { email: userB.email, role: 'member' },
    });
    expect(invite.ok()).toBeTruthy();
    expect((await invite.json()).status).toBe('invite_sent');

    const avisos = await (await contextB.request.get(`${API}/notifications`)).json();
    const convite = avisos.items.find((n: { invite_token?: string }) => n.invite_token);
    expect(convite, 'B recebeu a notificação do convite').toBeTruthy();
    const aceite = await contextB.request.post(`${API}/invites/accept/${convite.invite_token}`);
    expect(aceite.ok()).toBeTruthy();

    // --- Ambos abrem o app ---
    const pageA = await contextA.newPage();
    const pageB = await contextB.newPage();

    await pageA.goto('/');
    await expect(pageA.getByRole('heading', { name: /Hoje|Painel/ })).toBeVisible();

    await pageB.goto('/');
    await expect(pageB.getByRole('heading', { name: /Hoje|Painel/ })).toBeVisible();

    // B troca para o workspace compartilhado pelo switcher do sidebar — SEM
    // reload. O `reload()` que ficava aqui era maquiagem: escondia o defeito de
    // o socket novo adotar `hello.seq` como marco sem saber se o cache
    // correspondia a ele (mutação publicada na janela do handshake sumia até o
    // F5, e parecia "socket que recebe o hello e mais nada"). A janela em si tem
    // gate próprio em realtime_switch.spec.ts.
    const socketCompartilhado = pageB.waitForEvent('websocket', {
      predicate: (w) => w.url().includes(`/ws/workspaces/${wsA.id}`),
      timeout: 20_000,
    });
    // O seletor de escopo (`ScopeSwitcher`) substituiu o antigo
    // `WorkspaceSwitcher`: ele mostra o NOME do espaço atual, não a palavra
    // "Workspace" — que saiu da interface junto com o resto do jargão.
    await pageB.getByRole('button', { name: /Meu espaço|Pessoal/i }).first().click();
    await pageB.getByRole('button', { name: sharedWsName }).click();
    await expect(pageB.getByRole('button', { name: new RegExp(sharedWsName) })).toBeVisible();

    // Este spec mede ENTREGA AO VIVO, então espera o socket do workspace novo
    // abrir (a página pinta antes do handshake; o cliente só ouve depois do
    // `hello`). Se a mutação caísse na janela, quem cobre é o outro spec.
    await socketCompartilhado;
    await pageB.waitForTimeout(500);

    // --- Tempo real: A cria transação via API; B vê SEM reload ---
    const titleLive = `Jantar Tempo Real ${ts}`;

    // Ids dos dois: A paga e a despesa é DIVIDIDA com B.
    //
    // O split de B não é detalhe do cenário, é o que torna a despesa visível a
    // ele: B entrou como `member` + `involved_only` (ADR 0018), então uma despesa
    // só de A é invisível para B — e este spec mede ENTREGA AO VIVO, não
    // privacidade. Rateando, o que se testa continua sendo o WebSocket.
    // A privacidade em si tem gate próprio em `test_privacy_matrix.py`.
    const meA = await (await contextA.request.get(`${API}/auth/me`)).json();
    const meB = await (await contextB.request.get(`${API}/auth/me`)).json();
    const createTxAs = (title: string) =>
      contextA.request.post(`${API}/workspaces/${wsA.id}/transactions/`, {
        data: {
          title,
          total_amount: '90.00',
          transaction_date: new Date().toISOString(),
          payers: [{ user_id: meA.id, amount: '90.00' }],
          splits: [
            { user_id: meA.id, split_method: 'equal', input_value: '0' },
            { user_id: meB.id, split_method: 'equal', input_value: '0' },
          ],
        },
      });

    const res = await createTxAs(titleLive);
    expect(res.ok()).toBeTruthy();

    // B vê a transação nova sem qualquer reload (WebSocket → invalidation)
    await expect(pageB.getByText(titleLive)).toBeVisible({ timeout: 15_000 });

    // --- Resync: B fica offline, A cria 2 transações, B volta e converge ---
    await contextB.setOffline(true);
    const titleOffline1 = `Offline Um ${ts}`;
    const titleOffline2 = `Offline Dois ${ts}`;
    expect((await createTxAs(titleOffline1)).ok()).toBeTruthy();
    expect((await createTxAs(titleOffline2)).ok()).toBeTruthy();

    // Garante que B NÃO vê ainda (está offline)
    await expect(pageB.getByText(titleOffline1)).not.toBeVisible();

    await contextB.setOffline(false);
    // Reconexão (backoff) → hello.seq à frente → resync completo
    await expect(pageB.getByText(titleOffline1)).toBeVisible({ timeout: 30_000 });
    await expect(pageB.getByText(titleOffline2)).toBeVisible({ timeout: 10_000 });

    await contextA.close();
    await contextB.close();
  });
});
