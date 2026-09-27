import { test, expect, type BrowserContext } from '@playwright/test';

const API = 'http://localhost:8000/api/v1';

/**
 * A carga de página e o primeiro `hello` do WebSocket (auditoria 2026-09-26, P2).
 *
 * Antes, o primeiro `hello` de cada espaço refazia TODAS as consultas, em toda
 * carga de página: medido, 14 requisições e as mesmas 14 de novo meio segundo
 * depois. O motivo era real — uma mutação entre o GET da página e a entrada do
 * socket na sala ficaria invisível —, e o remédio agora é mais estreito: o seq
 * lido no bootstrap (antes de a página buscar qualquer dado) é comparado com o
 * do `hello`; só há resync se forem diferentes.
 *
 * Os dois lados do contrato, medidos aqui:
 *   1. a mutação que cai na janela do handshake continua aparecendo sem reload;
 *   2. sem mutação no meio, nenhuma consulta é feita duas vezes.
 */
test.describe('Carga de página: primeiro hello', () => {
  const ts = Date.now();

  async function contaNova(context: BrowserContext, nome: string) {
    const user = { name: nome, email: `${nome.toLowerCase()}${ts}@e2e.com`, password: 'senha123' };
    expect((await context.request.post(`${API}/auth/register`, { data: user })).ok()).toBeTruthy();
    expect((await context.request.post(`${API}/auth/login`, {
      data: { email: user.email, password: user.password },
    })).ok()).toBeTruthy();
    const [ws] = await (await context.request.get(`${API}/workspaces/`)).json();
    await context.request.post(`${API}/auth/onboarding`, { data: { workspace_id: ws.id, salary: 5000 } });
    const me = await (await context.request.get(`${API}/auth/me`)).json();
    return { ws, me };
  }

  test('mutação durante o handshake da carga aparece sem reload', async ({ browser }) => {
    test.setTimeout(120_000);
    const context = await browser.newContext();
    const { ws, me } = await contaNova(context, 'Carga');
    const page = await context.newPage();

    // Escancara a janela: o socket só entra na sala 4 s depois de a página
    // ter buscado os dados dela.
    await page.routeWebSocket(new RegExp(`/ws/workspaces/${ws.id}$`), async (sock) => {
      await new Promise((ok) => setTimeout(ok, 4000));
      sock.connectToServer();
    });

    await page.goto(`/w/${ws.id}`);
    await expect(page.getByRole('heading', { name: /Painel|Hoje/ })).toBeVisible();
    await page.waitForTimeout(1000);

    // Dentro da janela: a página já respondeu, o socket ainda não chegou.
    const titulo = `Na Janela da Carga ${ts}`;
    const res = await context.request.post(`${API}/workspaces/${ws.id}/transactions/`, {
      data: {
        title: titulo, total_amount: '42.00', transaction_date: new Date().toISOString(),
        payers: [{ user_id: me.id, amount: '42.00' }],
        splits: [{ user_id: me.id, split_method: 'equal', input_value: '0' }],
      },
    });
    expect(res.ok()).toBeTruthy();

    // O `hello` chega com o seq à frente do bootstrap → resync → aparece.
    await expect(page.getByText(titulo)).toBeVisible({ timeout: 30_000 });
    await context.close();
  });

  test('sem mutação no meio, nenhuma consulta é feita duas vezes', async ({ browser }) => {
    test.setTimeout(120_000);
    const context = await browser.newContext();
    const { ws } = await contaNova(context, 'Contagem');
    const page = await context.newPage();

    const pedidos: string[] = [];
    page.on('request', (req) => {
      const url = new URL(req.url());
      if (req.method() === 'GET' && url.pathname.startsWith('/api/v1/')) {
        pedidos.push(`${url.pathname}${url.search}`);
      }
    });
    const socket = page.waitForEvent('websocket', {
      predicate: (w) => w.url().includes(`/ws/workspaces/${ws.id}`),
    });

    await page.goto('/overview');
    await expect(page.getByRole('heading', { name: /Hoje|Início/ })).toBeVisible();
    await socket;
    // Tempo para o `hello` chegar e um eventual resync (debounce de 250 ms)
    // disparar as consultas de novo — é isso que não pode acontecer.
    await page.waitForTimeout(3000);

    const repetidos = [...new Set(pedidos.filter((p, i) => pedidos.indexOf(p) !== i))];
    console.log(`[P2] /overview: ${pedidos.length} consultas; repetidas: ${JSON.stringify(repetidos)}`);
    expect(pedidos.length).toBeGreaterThan(5); // a medição enxerga a carga
    expect(repetidos).toEqual([]);
    await context.close();
  });
});
