import { test, expect, type BrowserContext } from '@playwright/test';

const API = 'http://localhost:8000/api/v1';

/*
 * "Passo um tempo sem entrar, volto, e a tela fica preta, como se tentasse
 * carregar, mas não mostra nada. Preciso dar F5, ou fechar e abrir."
 *
 * Reproduzido no build de produção: bastava a primeira leva de requisições sair
 * por uma conexão que morreu enquanto o aparelho dormia. Sem prazo no cliente
 * HTTP, o `/auth/me` da carga nunca terminava, e o guard de rota mostrava
 * "Carregando sua sessão…" sobre o fundo escuro para sempre. O F5 resolvia porque
 * abria conexões novas.
 *
 * Aqui a conexão morta é a rota que nunca responde. O que se mede é a SAÍDA: a
 * tela avisa que está demorando, e a carga se recupera sozinha, sem F5.
 */
test.describe('A volta do aparelho', () => {
  const ts = Date.now();

  async function contaNova(context: BrowserContext, nome: string) {
    const user = { name: nome, email: `${nome.toLowerCase()}${ts}@e2e.com`, password: 'senha123' };
    expect((await context.request.post(`${API}/auth/register`, { data: user })).ok()).toBeTruthy();
    expect((await context.request.post(`${API}/auth/login`, {
      data: { email: user.email, password: user.password },
    })).ok()).toBeTruthy();
    const [ws] = await (await context.request.get(`${API}/workspaces/`)).json();
    await context.request.post(`${API}/auth/onboarding`, { data: { workspace_id: ws.id, salary: 5000 } });
  }

  test('a sessão pendurada numa conexão morta não prende a tela: avisa e se recupera sozinha', async ({ browser }) => {
    test.setTimeout(90_000);
    const context = await browser.newContext();
    await contaNova(context, 'Pendurada');
    const page = await context.newPage();

    // A primeira consulta de sessão nunca responde; as seguintes, sim — como
    // uma conexão velha morta e as novas funcionando.
    let consultas = 0;
    await page.route('**/api/v1/auth/me', async (rota) => {
      consultas += 1;
      if (consultas === 1) return; // pendurada: nem sucesso, nem erro
      await rota.continue();
    });

    await page.goto('/overview');
    await expect(page.getByText('Carregando sua sessão...')).toBeVisible();

    // Antes do prazo estourar, a tela já diz o que está acontecendo e dá a saída.
    await expect(page.getByText(/demorando mais que o normal/i)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole('button', { name: 'Recarregar' })).toBeVisible();

    // E não precisa dela: o prazo vence, a sessão é pedida de novo, e o app abre.
    await expect(page.getByRole('heading', { name: 'Hoje' })).toBeVisible({ timeout: 30_000 });
    expect(consultas).toBeGreaterThanOrEqual(2);
    await context.close();
  });

  test('falha de rede na renovação não desloga quem tem sessão válida', async ({ browser }) => {
    /*
     * O token de acesso venceu enquanto o app estava parado, e a renovação
     * volta 502 (o túnel no meio de um deploy, a rede do celular voltando).
     * Antes, qualquer falha da renovação era tratada como "sessão expirada":
     * a pessoa ia para "Bem-vindo, entre com suas credenciais".
     */
    test.setTimeout(60_000);
    const context = await browser.newContext();
    await contaNova(context, 'Renovacao');
    await context.clearCookies({ name: 'access_token' });
    const page = await context.newPage();

    let renovacoes = 0;
    await page.route('**/api/v1/auth/refresh', async (rota) => {
      renovacoes += 1;
      if (renovacoes === 1) {
        await rota.fulfill({ status: 502, contentType: 'text/html', body: '<h1>502 Bad Gateway</h1>' });
        return;
      }
      await rota.continue();
    });

    await page.goto('/overview');

    await expect(page.getByRole('heading', { name: 'Hoje' })).toBeVisible({ timeout: 30_000 });
    await expect(page).toHaveURL(/\/overview/);
    expect(renovacoes).toBeGreaterThanOrEqual(2);
    await context.close();
  });
});
