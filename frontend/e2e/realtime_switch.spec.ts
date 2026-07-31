import { test, expect, type BrowserContext } from '@playwright/test';

const API = 'http://localhost:8000/api/v1';

/**
 * Gate da JANELA DO HANDSHAKE na troca de workspace.
 *
 * Trocar de workspace faz duas coisas ao mesmo tempo: refaz as queries (HTTP) e
 * abre um socket novo. Uma mutação de outro membro commitada entre as duas some
 * da tela sem deixar rastro — o `hello` chega com o seq JÁ contando o evento, o
 * cliente se considera em dia e o próximo evento vem em ordem (nenhuma lacuna
 * para detectar). O sintoma era "o socket novo recebe o hello e nenhum evento
 * depois; só volta com F5".
 *
 * A correção tem duas metades e este spec cobre as duas:
 *   - servidor: o socket entra na sala ANTES de o seq do `hello` ser lido;
 *   - cliente: o primeiro `hello` de um workspace força resync completo, porque
 *     o cache veio por HTTP sem correlação alguma com o seq.
 *
 * A janela (centenas de ms na vida real) é ampliada de propósito com
 * `routeWebSocket`, senão o teste viraria corrida de timing.
 */
test.describe('Troca de workspace: janela do handshake', () => {
  const ts = Date.now();
  const userA = { name: 'Alice SW', email: `alicesw${ts}@e2e.com`, password: 'senha123' };
  const userB = { name: 'Bruno SW', email: `brunosw${ts}@e2e.com`, password: 'senha123' };
  const sharedWsName = `Trocado ${ts}`;
  const HANDSHAKE_DELAY_MS = 4000;

  async function registerAndLogin(context: BrowserContext, user: typeof userA) {
    expect((await context.request.post(`${API}/auth/register`, { data: user })).ok()).toBeTruthy();
    expect(
      (await context.request.post(`${API}/auth/login`, {
        data: { email: user.email, password: user.password },
      })).ok(),
    ).toBeTruthy();
  }

  test('mutação publicada durante o handshake aparece sem reload', async ({ browser }) => {
    test.setTimeout(180_000);
    const contextA = await browser.newContext();
    const contextB = await browser.newContext();

    await registerAndLogin(contextA, userA);
    await registerAndLogin(contextB, userB);

    const [wsA] = await (await contextA.request.get(`${API}/workspaces/`)).json();
    await contextA.request.post(`${API}/auth/onboarding`, {
      data: { workspace_id: wsA.id, salary: 5000 },
    });
    const [wsB] = await (await contextB.request.get(`${API}/workspaces/`)).json();
    await contextB.request.post(`${API}/auth/onboarding`, {
      data: { workspace_id: wsB.id, salary: 5000 },
    });

    // A compartilha o workspace com B (convite exige aceite desde o E15)
    await contextA.request.put(`${API}/workspaces/${wsA.id}`, { data: { name: sharedWsName } });
    expect(
      (await contextA.request.post(`${API}/workspaces/${wsA.id}/invites`, {
        data: { email: userB.email, role: 'member' },
      })).ok(),
    ).toBeTruthy();
    const avisos = await (await contextB.request.get(`${API}/notifications`)).json();
    const convite = avisos.items.find((n: { invite_token?: string }) => n.invite_token);
    expect(convite, 'B recebeu a notificação do convite').toBeTruthy();
    expect(
      (await contextB.request.post(`${API}/invites/accept/${convite.invite_token}`)).ok(),
    ).toBeTruthy();

    // A paga e RATEIA com B: B entrou como `member` + `involved_only` (ADR 0018),
    // então despesa só de A é invisível para ele. Este spec mede a janela do
    // handshake, não privacidade — sem o split, ele passaria a falhar por um
    // motivo que não é o dele.
    const meA = await (await contextA.request.get(`${API}/auth/me`)).json();
    const meB = await (await contextB.request.get(`${API}/auth/me`)).json();
    const createTx = (title: string) =>
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

    const pageB = await contextB.newPage();
    // Atrasa SÓ o handshake do socket do workspace compartilhado: escancara a
    // janela entre o refetch da troca e a entrada do socket na sala.
    await pageB.routeWebSocket(new RegExp(`/ws/workspaces/${wsA.id}$`), async (ws) => {
      await new Promise((resolve) => setTimeout(resolve, HANDSHAKE_DELAY_MS));
      ws.connectToServer();
    });

    await pageB.goto('/');
    await expect(pageB.getByRole('heading', { name: /Workspace ·|Início|Painel/ })).toBeVisible();
    // Pré-condição: B está no próprio workspace, com socket aberto
    await pageB.waitForEvent('websocket', {
      predicate: (w) => w.url().includes(`/ws/workspaces/${wsB.id}`),
      timeout: 20_000,
    });

    // Troca pelo switcher do sidebar
    await pageB.getByRole('button', { name: /Workspace|Selecione/i }).first().click();
    await pageB.getByRole('button', { name: sharedWsName }).click();
    await expect(pageB.getByRole('button', { name: new RegExp(sharedWsName) })).toBeVisible();

    // Dentro da janela: o refetch da troca já respondeu, o socket ainda não
    // entrou na sala. Este lançamento é o que sumia até o F5.
    await pageB.waitForTimeout(1500);
    const titulo = `Na Janela ${ts}`;
    expect((await createTx(titulo)).ok()).toBeTruthy();

    // Sem reload nem interação: o resync do primeiro `hello` traz o lançamento
    await expect(pageB.getByText(titulo)).toBeVisible({ timeout: 30_000 });

    // E o tempo real segue vivo no socket novo (entrega ao vivo, já na sala)
    const tituloAoVivo = `Ao Vivo ${ts}`;
    expect((await createTx(tituloAoVivo)).ok()).toBeTruthy();
    await expect(pageB.getByText(tituloAoVivo)).toBeVisible({ timeout: 15_000 });

    await contextA.close();
    await contextB.close();
  });
});
