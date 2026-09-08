import { test, expect, type Browser } from '@playwright/test';

/**
 * Busca global — a pergunta "onde foi aquele pagamento do dentista?".
 *
 * O app tinha cinco listas e nenhuma que atravessasse as outras: achar um
 * lançamento de três meses atrás exigia lembrar em qual espaço ele foi e navegar
 * até o mês certo. Quem não lembra o mês não tinha caminho nenhum.
 *
 * A visibilidade (ADR 0018) é trancada no backend, onde ela é decidida —
 * `tests/security/test_busca_respeita_visibilidade.py`, escrito antes da rota.
 * Aqui o assunto é outro: o caminho existe, o atalho abre, e a linha LEVA a
 * algum lugar. Uma busca que acha e não leva não resolve nada.
 */
const API = 'http://localhost:8000/api/v1';

async function contaComLancamento(browser: Browser, titulo: string) {
  const ts = Date.now() + Math.floor(Math.random() * 1000);
  const email = `busca${ts}@e2e.com`;
  const context = await browser.newContext({ viewport: { width: 1366, height: 800 } });
  const api = context.request;

  await api.post(`${API}/auth/register`, { data: { name: 'Nina Busca', email, password: 'senha123' } });
  await api.post(`${API}/auth/login`, { data: { email, password: 'senha123' } });
  await api.post(`${API}/auth/onboarding`, { data: { salary: 5000 } });
  const [ws] = await (await api.get(`${API}/workspaces/`)).json();
  const eu = await (await api.get(`${API}/auth/me`)).json();

  await api.post(`${API}/workspaces/${ws.id}/transactions/`, {
    data: {
      title: titulo,
      total_amount: '380.00',
      transaction_date: new Date().toISOString(),
      payment_method: 'pix',
      settled: true,
      payers: [{ user_id: eu.id, amount: '380.00' }],
      splits: [{ user_id: eu.id, split_method: 'equal', input_value: '0' }],
    },
  });

  return { context, wsId: ws.id as number };
}

test('acha um lançamento de qualquer tela, pelo atalho do teclado', async ({ browser }) => {
  const { context } = await contaComLancamento(browser, 'Dentista da Ana');
  const page = await context.newPage();

  // De uma tela QUALQUER — a graça é não precisar estar na lista certa.
  await page.goto('/me/cards');
  await page.waitForLoadState('networkidle');

  await page.keyboard.press('/');
  const dialogo = page.getByRole('dialog');
  await expect(dialogo).toBeVisible();

  await dialogo.getByLabel('Buscar em tudo').fill('dentista');
  await expect(dialogo.getByText('Dentista da Ana')).toBeVisible({ timeout: 10_000 });

  await context.close();
});

test('a linha leva ao lançamento, não só o mostra', async ({ browser }) => {
  const { context, wsId } = await contaComLancamento(browser, 'Dentista da Ana');
  const page = await context.newPage();
  await page.goto('/overview');
  await page.waitForLoadState('networkidle');

  await page.keyboard.press('/');
  const dialogo = page.getByRole('dialog');
  await dialogo.getByLabel('Buscar em tudo').fill('dentista');
  await dialogo.getByText('Dentista da Ana').click();

  await expect(page).toHaveURL(new RegExp(`/w/${wsId}/transactions`));
  await expect(page.getByText('Dentista da Ana').first()).toBeVisible();

  await context.close();
});

test('a barra não vira atalho no meio de um texto', async ({ browser }) => {
  const { context, wsId } = await contaComLancamento(browser, 'Dentista da Ana');
  const page = await context.newPage();
  await page.goto(`/w/${wsId}/transactions`);
  await page.waitForLoadState('networkidle');

  // CONTROLE, primeiro: nesta mesma tela, a barra FORA de campo abre a busca.
  // Sem esta metade, o teste passaria num app sem busca nenhuma — "não abriu
  // diálogo" é verdade também quando não há diálogo para abrir.
  await page.keyboard.press('/');
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);

  // E DENTRO de um campo ela é só uma barra: digitar "23/09" na busca da lista
  // não pode abrir nada, senão o app come o que a pessoa está escrevendo.
  const campo = page.getByPlaceholder(/Buscar por descrição/i);
  await campo.click();
  await campo.pressSequentially('23/09');
  await expect(campo).toHaveValue('23/09');
  await expect(page.getByRole('dialog')).toHaveCount(0);

  await context.close();
});

/**
 * Desfazer a exclusão — o portão que o plano exige: excluir, desfazer, a linha
 * volta.
 *
 * A confirmação saiu de propósito: perguntar "tem certeza?" a cada exclusão
 * treina a pessoa a responder "sim" sem ler, e a partir daí ela não protege
 * mais nada. O desfazer protege de verdade e não cobra nada de quem acertou.
 */
test('excluir por engano tem volta', async ({ browser }) => {
  const { context, wsId } = await contaComLancamento(browser, 'Dentista da Ana');
  const page = await context.newPage();
  await page.goto(`/w/${wsId}/transactions`);
  await page.waitForLoadState('networkidle');

  const linha = page.getByTestId('ledger-row').filter({ hasText: 'Dentista da Ana' });
  await expect(linha).toBeVisible();
  await linha.getByRole('button', { name: /excluir transação/i }).click();

  // Sem diálogo de confirmação no caminho: a exclusão acontece e o aviso oferece
  // a volta.
  await expect(page.getByText('Lançamento removido')).toBeVisible();
  await expect(page.getByTestId('ledger-row').filter({ hasText: 'Dentista da Ana' }))
    .toHaveCount(0);

  await page.getByRole('button', { name: 'Desfazer' }).click();

  await expect(page.getByTestId('ledger-row').filter({ hasText: 'Dentista da Ana' }))
    .toBeVisible({ timeout: 10_000 });

  await context.close();
});

/**
 * Categorizar em lote — a resposta prática ao "Maior categoria: Sem categoria".
 *
 * Chegar à lista do que falta categorizar já existe (o filtro "Sem categoria",
 * com rota própria no backend). O que faltava era conseguir resolver trinta
 * linhas sem abrir trinta vezes o detalhe — que é a razão de a categoria ficar
 * vazia: não falta vontade, sobra custo.
 */
test('categoriza vários lançamentos de uma vez', async ({ browser }) => {
  const { context, wsId } = await contaComLancamento(browser, 'Padaria da esquina');
  const page = await context.newPage();

  // Uma categoria para aplicar.
  await context.request.post(`${API}/workspaces/${wsId}/categories`, {
    data: { name: 'Alimentação' },
  });

  await page.goto(`/w/${wsId}/transactions`);
  await page.waitForLoadState('networkidle');

  // Fora do modo, a lista NÃO tem caixa de seleção: quem só quer olhar o mês
  // não paga por uma função usada uma vez por trimestre.
  await expect(page.getByRole('checkbox', { name: /Selecionar Padaria/ })).toHaveCount(0);

  await page.getByRole('button', { name: /selecionar vários/i }).click();
  await page.getByRole('checkbox', { name: /Selecionar Padaria/ }).check();
  await expect(page.getByText('1 selecionado(s)')).toBeVisible();

  await page.getByLabel('Categoria a aplicar').selectOption({ label: 'Alimentação' });
  await page.getByRole('button', { name: 'Aplicar' }).click();

  await expect(page.getByText('1 lançamento(s) categorizado(s)')).toBeVisible();

  // E o filtro "Sem categoria" deixa de trazê-lo — que é o efeito que importa.
  await page.goto(`/w/${wsId}/transactions?semcategoria=sim`);
  await expect(page.getByTestId('ledger-row').filter({ hasText: 'Padaria da esquina' }))
    .toHaveCount(0);

  await context.close();
});
