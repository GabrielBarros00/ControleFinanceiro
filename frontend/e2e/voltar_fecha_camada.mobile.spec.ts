import { test, expect, type Page } from '@playwright/test';

/*
 * No celular, VOLTAR fecha o que está por cima — não sai da página.
 *
 * O relato do dono: com a gaveta "Mais" aberta, apertar voltar levava para a
 * página anterior e a gaveta ia junto. Perder a tela em que se está para fechar
 * um menu é caro, e "voltar" é o gesto mais usado do aparelho.
 *
 * Ao investigar, o defeito não era da gaveta: valia para QUALQUER sobreposição
 * (verificado também em "Nova despesa"). Por isso a correção mora no primitivo
 * `ui/dialog.tsx`, e por isso este portão mede os dois — se alguém "otimizar" o
 * hook para um caso só, o outro reprova.
 *
 * ## O que cada caso protege
 *
 * 1. **Voltar fecha e a página fica.** O defeito original.
 * 2. **O segundo voltar navega.** A correção empilha uma entrada de histórico;
 *    se ela não for desempilhada, o próximo voltar "não faz nada" — que é um
 *    defeito pior, porque parece o app travado.
 * 3. **Fechar por outro caminho não deixa entrada órfã.** Mesmo risco do caso 2,
 *    pela outra porta (Escape, X, clique fora).
 * 4. **Abrir e fechar em sequência.** Em desenvolvimento o React monta o efeito
 *    duas vezes, e uma implementação ingênua fecha a camada sozinha logo depois
 *    de abrir. Este caso é a diferença entre "funciona" e "funciona no modo
 *    estrito também".
 */
const API = 'http://localhost:8000/api/v1';

async function contaComEspaco(page: Page) {
  const ts = Date.now() + Math.floor(Math.random() * 1000);
  const email = `voltar${ts}@e2e.com`;
  const api = page.context().request;
  await api.post(`${API}/auth/register`, { data: { name: 'Vera Voltar', email, password: 'senha123' } });
  await api.post(`${API}/auth/login`, { data: { email, password: 'senha123' } });
  await api.post(`${API}/auth/onboarding`, { data: { salary: 4000 } });
  const [ws] = await (await api.get(`${API}/workspaces/`)).json();
  return ws.id as number;
}

/** Duas páginas no histórico: sem isso "voltar" não tem para onde ir e o teste não mede nada. */
async function comHistorico(page: Page, wsId: number) {
  await page.goto('/overview');
  await page.goto(`/w/${wsId}/transactions`);
  await expect(page.getByRole('heading', { name: 'Lançamentos' })).toBeVisible();
}

const gaveta = (page: Page) => page.getByRole('button', { name: /mais/i }).last();
const camadas = (page: Page) => page.locator('[role="dialog"]');

test('voltar fecha a gaveta "Mais" e mantém a página', async ({ page }) => {
  const wsId = await contaComEspaco(page);
  await comHistorico(page, wsId);

  await gaveta(page).click();
  await expect(camadas(page)).toHaveCount(1);

  await page.goBack();

  await expect(camadas(page), 'a gaveta devia ter fechado').toHaveCount(0);
  await expect(page, 'voltar não podia ter saído da página').toHaveURL(
    new RegExp(`/w/${wsId}/transactions`),
  );
});

test('depois de fechar pelo voltar, o próximo voltar navega de verdade', async ({ page }) => {
  const wsId = await contaComEspaco(page);
  await comHistorico(page, wsId);

  await gaveta(page).click();
  await expect(camadas(page)).toHaveCount(1);
  await page.goBack();
  await expect(camadas(page)).toHaveCount(0);

  await page.goBack();
  await expect(
    page,
    'a entrada de histórico da camada ficou pendurada: o voltar seguinte não levou a lugar nenhum',
  ).toHaveURL(/\/overview/);
});

test('fechar pelo Escape não deixa entrada de histórico órfã', async ({ page }) => {
  const wsId = await contaComEspaco(page);
  await comHistorico(page, wsId);

  await gaveta(page).click();
  await expect(camadas(page)).toHaveCount(1);
  await page.keyboard.press('Escape');
  await expect(camadas(page)).toHaveCount(0);

  await page.goBack();
  await expect(
    page,
    'a camada foi fechada por outro caminho e a entrada dela sobrou na pilha',
  ).toHaveURL(/\/overview/);
});

test('voltar fecha o formulário de Nova despesa (vale para toda camada, não só a gaveta)', async ({ page }) => {
  const wsId = await contaComEspaco(page);
  await comHistorico(page, wsId);

  await page.getByRole('button', { name: /nova despesa/i }).first().click();
  await expect(page.getByRole('heading', { name: /nova despesa/i })).toBeVisible();

  await page.goBack();

  await expect(camadas(page)).toHaveCount(0);
  await expect(page).toHaveURL(new RegExp(`/w/${wsId}/transactions`));
});

test('a gaveta abre três vezes seguidas sem se fechar sozinha', async ({ page }) => {
  const wsId = await contaComEspaco(page);
  await comHistorico(page, wsId);

  for (let vez = 1; vez <= 3; vez += 1) {
    await gaveta(page).click();
    await expect(
      camadas(page),
      `abertura ${vez}: a gaveta se fechou sozinha — sinal de que o "voltar" `
      + 'programático da limpeza foi confundido com o da pessoa',
    ).toHaveCount(1);
    await page.keyboard.press('Escape');
    await expect(camadas(page)).toHaveCount(0);
  }
});
