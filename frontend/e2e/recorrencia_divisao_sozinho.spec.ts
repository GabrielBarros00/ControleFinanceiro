import { test, expect, type Browser } from '@playwright/test';

/**
 * "Dividir com" quando NÃO há com quem dividir.
 *
 * A tela esconde o bloco abaixo de dois membros — perguntar "dividir com quem?"
 * a quem está sozinho no espaço é oferecer uma escolha que não existe. Este
 * teste tranca essa decisão nos dois sentidos, porque ela é indistinguível de
 * um defeito para quem abre o formulário: quem não sabe da regra vê a mesma
 * coisa que veria se a funcionalidade estivesse quebrada.
 *
 * É a resposta a "por que ainda não consigo dividir?": no espaço PESSOAL, que é
 * onde a maioria abre o app, não há segunda pessoa — e o bloco não aparece por
 * decisão, não por falha.
 */
const API = 'http://localhost:8000/api/v1';

async function conta(browser: Browser, nome: string) {
  const ts = Date.now() + Math.floor(Math.random() * 1000);
  const email = `so${ts}@e2e.com`;
  const context = await browser.newContext({ viewport: { width: 1366, height: 900 } });
  const api = context.request;
  await api.post(`${API}/auth/register`, { data: { name: nome, email, password: 'senha123' } });
  await api.post(`${API}/auth/login`, { data: { email, password: 'senha123' } });
  await api.post(`${API}/auth/onboarding`, { data: {} });
  const [ws] = await (await api.get(`${API}/workspaces/`)).json();
  return { context, wsId: ws.id as number, email };
}

test('sozinho no espaço, o formulário EXPLICA em vez de esconder', async ({ browser }) => {
  /*
   * A primeira versão escondia o bloco inteiro — e o dono do projeto abriu o
   * formulário no espaço pessoal dele (uma pessoa só), não viu nada, e
   * perguntou "por que ainda não consigo dividir?". Do lado de quem olha,
   * "escondido por decisão" e "quebrado" são a mesma tela.
   *
   * Some o que não dá para fazer (as pílulas), fica o que explica por quê.
   */
  const { context, wsId } = await conta(browser, 'Sozinha');
  const page = await context.newPage();

  await page.goto(`/w/${wsId}/recurring`);
  await page.getByRole('button', { name: /nova despesa/i }).first().click();
  const dialogo = page.getByRole('dialog');
  await expect(dialogo).toBeVisible();

  await expect(dialogo.getByText('Dividir com')).toBeVisible();
  await expect(dialogo.getByText(/única pessoa neste espaço/i)).toBeVisible();
  // O caminho para resolver, e não só o aviso.
  await expect(dialogo.getByRole('link', { name: /convidar/i })).toBeVisible();

  await context.close();
});

test('com uma segunda pessoa no espaço, o bloco aparece', async ({ browser }) => {
  /* O par do teste acima. Sem ele, "esconder sempre" passaria — e seria
     exatamente o defeito que a pessoa relataria. */
  const anfitria = await conta(browser, 'Anfitriã');
  const convidado = await conta(browser, 'Convidado');

  await anfitria.context.request.post(`${API}/workspaces/${anfitria.wsId}/invites`, {
    data: { email: convidado.email, role: 'member' },
  });
  const avisos = await (await convidado.context.request.get(`${API}/notifications`)).json();
  const token = avisos.items.find((n: { invite_token?: string }) => n.invite_token)?.invite_token;
  expect(token, 'o convite chegou').toBeTruthy();
  expect((await convidado.context.request.post(`${API}/invites/accept/${token}`)).ok()).toBeTruthy();

  const page = await anfitria.context.newPage();
  await page.goto(`/w/${anfitria.wsId}/recurring`);
  await page.getByRole('button', { name: /nova despesa/i }).first().click();
  const dialogo = page.getByRole('dialog');

  await expect(dialogo.getByText('Dividir com')).toBeVisible();
  await expect(dialogo.getByRole('button', { name: 'Convidado' })).toBeVisible();

  await anfitria.context.close();
  await convidado.context.close();
});
