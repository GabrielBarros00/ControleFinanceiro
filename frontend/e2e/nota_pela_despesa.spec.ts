import { test, expect } from '@playwright/test';

/**
 * O relato: "Adicionei uma compra, mas quando fui editar para verificar se tava
 * tudo certo, desde itens e valores, não mostrou nada."
 *
 * A compra veio pela IA (MCP), que grava uma nota em que nenhum item tem divisão
 * própria como divisão PELA DESPESA com itens e ajustes (`plan_items`). A tela
 * só conhecia itens na divisão por item: o detalhe mostrava o desconto sem a
 * compra, a edição abria sem nota nenhuma, e salvar — até para trocar só o
 * título — mandava o item-sombra no lugar do combo e nenhum ajuste, e a edição
 * completa apagava os dois do banco.
 *
 * A semeadura vai pela API REST com o mesmo corpo que o comando do MCP recebe; a
 * pergunta aqui é a do relato — a pessoa VÊ, e salvar não destrói.
 */
const API = 'http://localhost:8000/api/v1';

test('a nota lançada pela IA aparece no detalhe e na edição, e salvar a mantém', async ({ browser }) => {
  test.setTimeout(120_000);
  const ctx = await browser.newContext({ viewport: { width: 1366, height: 900 } });
  const quem = { name: 'Nota Tester', email: `nota_e2e_${Date.now()}@example.com`, password: 'senha123' };
  expect((await ctx.request.post(`${API}/auth/register`, { data: quem })).ok()).toBeTruthy();
  await ctx.request.post(`${API}/auth/login`, { data: { email: quem.email, password: quem.password } });
  const [ws] = await (await ctx.request.get(`${API}/workspaces/`)).json();
  await ctx.request.post(`${API}/auth/onboarding`, { data: { workspace_id: ws.id } });
  const eu = await (await ctx.request.get(`${API}/auth/me`)).json();

  const hoje = new Date();
  const dia = `${hoje.getFullYear()}-${String(hoje.getMonth() + 1).padStart(2, '0')}-${String(hoje.getDate()).padStart(2, '0')}`;
  const criada = await ctx.request.post(`${API}/workspaces/${ws.id}/transactions/`, {
    data: {
      title: "McDonald's E2E",
      description: 'Pedido nº 8509.',
      total_amount: '37.41',
      transaction_date: `${dia}T12:00:00`,
      payment_method: 'pix',
      settled: true,
      split_mode: 'transaction',
      payers: [{ user_id: eu.id, amount: '37.41' }],
      splits: [{ user_id: eu.id, split_method: 'equal', input_value: '0' }],
      items: [{
        title: 'Combo: Big Mac + Quarterão', description: 'Combo com 2 sanduíches.',
        amount: '37.90', quantity: '1', unit: 'un', unit_amount: '37.90', position: 0,
      }],
      adjustments: [
        { type: 'discount', amount: '-9.47', description: 'Desconto do pedido' },
        { type: 'shipping', amount: '7.99', description: 'Taxa de entrega' },
        { type: 'other', amount: '0.99', description: 'Taxa de serviço' },
      ],
    },
  });
  expect(criada.ok(), await criada.text()).toBeTruthy();
  const { id } = await criada.json();

  const page = await ctx.newPage();
  await page.goto('/transactions');
  const row = page.getByTestId('ledger-row').filter({ hasText: "McDonald's E2E" });
  await expect(row).toBeVisible({ timeout: 15_000 });

  // --- Detalhe: a compra aparece junto do desconto ---------------------------
  await row.getByRole('button', { name: "McDonald's E2E" }).click();
  const detalhe = page.getByRole('dialog');
  const itens = detalhe.getByTestId('summary-items');
  await expect(itens.getByText('Combo: Big Mac + Quarterão')).toBeVisible();
  await expect(itens.getByText(/1 un × R\$\s37,90/)).toBeVisible();
  await expect(detalhe.getByText(/Desconto \(Desconto do pedido\)/)).toBeVisible();
  await page.screenshot({ path: 'test-results/nota-pela-despesa-detalhe.png' });

  // --- Edição: itens e ajustes, sem abrir "Dividir por…" ---------------------
  await detalhe.getByRole('button', { name: 'Editar' }).click();
  const edicao = page.getByRole('dialog').filter({ hasText: 'Editar Transação' });
  await expect(edicao.getByTestId('items-editor').getByText('Itens da nota')).toBeVisible();
  await expect(edicao.getByLabel('Título do item')).toHaveValue('Combo: Big Mac + Quarterão');
  await expect(edicao.getByLabel('Total do item')).toHaveValue('37,90');
  await expect(edicao.getByLabel('Tipo do ajuste')).toHaveCount(3);
  await expect(edicao.getByLabel('Valor do ajuste').first()).toHaveValue('9,47');
  await expect(edicao.getByTestId('items-summary')).toContainText('fecham');
  await edicao.getByTestId('items-editor').scrollIntoViewIfNeeded();
  await page.screenshot({ path: 'test-results/nota-pela-despesa-edicao.png' });

  // --- Salvar mexendo só no título não apaga a nota ---------------------------
  await edicao.getByLabel('Título / Descrição').fill("McDonald's E2E conferido");
  await edicao.getByRole('button', { name: 'Salvar Alterações' }).click();
  await expect(edicao).not.toBeVisible({ timeout: 10_000 });

  const depois = await (await ctx.request.get(`${API}/workspaces/${ws.id}/transactions/${id}`)).json();
  expect(depois.title).toBe("McDonald's E2E conferido");
  expect(depois.total_amount).toBe('37.41');
  expect(depois.items.map((i: { title: string; amount: string }) => [i.title, i.amount]))
    .toEqual([['Combo: Big Mac + Quarterão', '37.90']]);
  expect(depois.adjustments.map((a: { type: string; amount: string }) => [a.type, a.amount]))
    .toEqual([['discount', '-9.47'], ['shipping', '7.99'], ['other', '0.99']]);

  // --- No celular, a nota cabe no diálogo -------------------------------------
  // O editor de ajustes é novo: tipo, valor com o sinal e a lixeira na mesma
  // linha a 360px não podem empurrar o diálogo para os lados.
  await page.setViewportSize({ width: 360, height: 780 });
  await row.getByRole('button', { name: "McDonald's E2E conferido" }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Editar' }).click();
  const celular = page.getByRole('dialog').filter({ hasText: 'Editar Transação' });
  const ajustes = celular.getByTestId('adjustments-editor');
  await ajustes.scrollIntoViewIfNeeded();
  await expect(ajustes.getByLabel('Valor do ajuste').first()).toBeVisible();
  const vaza = await celular.evaluate((el) => el.scrollWidth - el.clientWidth);
  expect(vaza, 'o diálogo de edição rola na horizontal a 360px').toBeLessThanOrEqual(0);
  await page.screenshot({ path: 'test-results/nota-pela-despesa-celular.png' });

  await ctx.close();
});
