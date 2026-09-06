import { test, expect, type BrowserContext } from '@playwright/test';

/**
 * Dividir uma despesa FIXA — e a divisão sobreviver à materialização.
 *
 * ## Por que o teste vai até a dívida, e não para no formulário
 *
 * A recorrência é o único lugar do app onde o que se cadastra hoje vira dado
 * **sozinho, meses depois**: a materialização é preguiçosa, e a ocorrência do
 * mês que vem nasce quando alguém abre uma tela de leitura. Conferir só que a
 * tela mandou `split_snapshot` provaria que o formulário funciona e não que o
 * aluguel dividido em dois vira dívida de verdade — que é a única coisa que a
 * pessoa queria.
 *
 * Por isso o caminho inteiro: Ana cadastra o aluguel dividido com o Bruno →
 * a ocorrência é gerada → Bruno deve metade.
 *
 * O serviço já tinha teste unitário disso (`test_recurring_snapshot.py`); o que
 * não existia era a ponta da tela, que é justamente o que faltava no produto.
 */
const API = 'http://localhost:8000/api/v1';

const ana = { name: 'Ana Divide', email: `ana-div${Date.now()}@e2e.com`, password: 'senha123' };
const bruno = { name: 'Bruno Divide', email: `bruno-div${Date.now()}@e2e.com`, password: 'senha123' };

async function registrar(ctx: BrowserContext, quem: typeof ana) {
  const r = await ctx.request.post(`${API}/auth/register`, { data: quem });
  expect(r.ok(), await r.text()).toBeTruthy();
  await ctx.request.post(`${API}/auth/login`, {
    data: { email: quem.email, password: quem.password },
  });
}

test('o aluguel dividido no template vira dívida em toda ocorrência', async ({ browser }) => {
  test.setTimeout(180_000);

  const ctxAna = await browser.newContext();
  const ctxBruno = await browser.newContext();
  await registrar(ctxAna, ana);
  await registrar(ctxBruno, bruno);

  const [ws] = await (await ctxAna.request.get(`${API}/workspaces/`)).json();
  await ctxAna.request.post(`${API}/auth/onboarding`, { data: { workspace_id: ws.id } });
  const [wsB] = await (await ctxBruno.request.get(`${API}/workspaces/`)).json();
  await ctxBruno.request.post(`${API}/auth/onboarding`, { data: { workspace_id: wsB.id } });

  // Bruno entra no espaço da Ana (o convite exige aceite — consentimento).
  await ctxAna.request.post(`${API}/workspaces/${ws.id}/invites`, {
    data: { email: bruno.email, role: 'member' },
  });
  const avisos = await (await ctxBruno.request.get(`${API}/notifications`)).json();
  const token = avisos.items.find((n: { invite_token?: string }) => n.invite_token)?.invite_token;
  expect(token, 'Bruno recebeu o convite').toBeTruthy();
  expect((await ctxBruno.request.post(`${API}/invites/accept/${token}`)).ok()).toBeTruthy();

  // --- Ana cadastra o aluguel, dividido com o Bruno, PELA TELA -------------
  const page = await ctxAna.newPage();
  await page.goto(`/w/${ws.id}/recurring`);
  await page.getByRole('button', { name: /nova despesa/i }).first().click();

  const dialogo = page.getByRole('dialog');
  await expect(dialogo).toBeVisible();
  await dialogo.getByLabel(/título/i).fill('Aluguel');
  await dialogo.getByLabel(/valor/i).first().fill('2.000,00');

  /*
   * "Começa em" no dia 1º deste mês.
   *
   * O padrão do formulário é `day_of_month: 1` com início HOJE — e a ocorrência
   * do dia 1º é anterior ao início, então a primeira só nasceria no mês que vem.
   * O teste ficaria esperando para sempre por um lançamento correto que ainda
   * não existe. Recuando o início, a ocorrência deste mês já venceu e a
   * materialização preguiçosa a cria na primeira tela de leitura.
   */
  const primeiroDoMes = (() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`;
  })();
  await dialogo.locator('#rec-preset-start').fill(primeiroDoMes);

  await dialogo.getByRole('button', { name: 'Ana Divide' }).click();
  await dialogo.getByRole('button', { name: 'Bruno Divide' }).click();
  await dialogo.getByRole('button', { name: /salvar/i }).click();
  await expect(dialogo).toBeHidden();

  // --- A ocorrência nasce dividida ----------------------------------------
  await page.goto(`/w/${ws.id}/transactions`);
  await expect(page.getByText('Aluguel').first()).toBeVisible();

  // --- E o Bruno deve metade ----------------------------------------------
  const dividas = await (await ctxAna.request.get(`${API}/workspaces/${ws.id}/debts`)).json();
  const linhas = JSON.stringify(dividas);
  expect(
    linhas,
    `esperava R$ 1.000,00 de dívida na lista, veio: ${linhas}`,
  ).toContain('1000.00');

  await ctxAna.close();
  await ctxBruno.close();
});
