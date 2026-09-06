import { test, expect, type BrowserContext } from '@playwright/test';
import { diaLocal } from '../e2e-shared/datas';

/**
 * O relato, percorrido pela tela.
 *
 * "Quando alguém registra um acerto em Seus Acertos › Resumo, ele não desconta o
 * valor devido: o mês continua lá, como 0 pago. Só desconta do total. Também não
 * tem opção de excluir ou corrigir o valor registrado."
 *
 * O backend tem os testes de cálculo (`test_acerto_fecha_os_meses.py`). Aqui a
 * pergunta é outra e é a do relato: **a pessoa vê o resultado?** Um acerto que
 * fecha o mês no banco e não fecha na tela é o mesmo defeito com outro nome.
 *
 * O caminho é o do relato inteiro: registrar pelo Resumo → o mês some da origem
 * do saldo → desfazer ali mesmo → a dívida volta.
 */
const API = 'http://localhost:8000/api/v1';

const ana = { name: 'Ana Acerto', email: `ana-ac${Date.now()}@e2e.com`, password: 'senha123' };
const bruno = { name: 'Bruno Acerto', email: `bruno-ac${Date.now()}@e2e.com`, password: 'senha123' };

async function registrar(ctx: BrowserContext, quem: typeof ana) {
  const r = await ctx.request.post(`${API}/auth/register`, { data: quem });
  expect(r.ok(), await r.text()).toBeTruthy();
  await ctx.request.post(`${API}/auth/login`, {
    data: { email: quem.email, password: quem.password },
  });
}

/** O dia 10 de N meses atrás — a dívida precisa vir de meses FECHADOS. */
function mesAtras(n: number): { iso: string; mes: string } {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - n);
  const mes = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  return { iso: `${mes}-10T12:00:00.000Z`, mes };
}

test('o acerto do Resumo fecha o mês na tela, e dá para desfazer ali mesmo', async ({ browser }) => {
  test.setTimeout(180_000);

  const ctxAna = await browser.newContext({ viewport: { width: 1366, height: 900 } });
  const ctxBruno = await browser.newContext();
  await registrar(ctxAna, ana);
  await registrar(ctxBruno, bruno);

  const [ws] = await (await ctxAna.request.get(`${API}/workspaces/`)).json();
  await ctxAna.request.post(`${API}/auth/onboarding`, { data: { workspace_id: ws.id } });
  const [wsB] = await (await ctxBruno.request.get(`${API}/workspaces/`)).json();
  await ctxBruno.request.post(`${API}/auth/onboarding`, { data: { workspace_id: wsB.id } });

  await ctxAna.request.post(`${API}/workspaces/${ws.id}/invites`, {
    data: { email: bruno.email, role: 'member' },
  });
  const avisos = await (await ctxBruno.request.get(`${API}/notifications`)).json();
  const token = avisos.items.find((n: { invite_token?: string }) => n.invite_token)?.invite_token;
  expect(token, 'Bruno recebeu o convite').toBeTruthy();
  expect((await ctxBruno.request.post(`${API}/invites/accept/${token}`)).ok()).toBeTruthy();

  const eu = await (await ctxAna.request.get(`${API}/auth/me`)).json();
  const outro = await (await ctxBruno.request.get(`${API}/auth/me`)).json();

  /*
   * DOIS meses, de propósito.
   *
   * A primeira versão deste teste usava um mês só e quitava a dívida inteira —
   * e passava com o defeito ligado, porque com o saldo zerado o bloco "de onde
   * vem esse saldo" simplesmente some da tela: "R$ 100,00 sumiu" era verdade
   * pelo motivo errado.
   *
   * Com dois meses e um acerto do tamanho do mais antigo, a tela TEM de
   * continuar mostrando o outro — o que distingue "o mês fechou" de "a seção
   * inteira desapareceu".
   *
   *   dois meses atrás: R$ 200 → Bruno deve 100   ← o acerto fecha este
   *   um mês atrás:     R$ 120 → Bruno deve  60   ← este continua na tela
   */
  const antigo = mesAtras(2);
  const recente = mesAtras(1);
  for (const [quando, valor] of [[antigo.iso, '200.00'], [recente.iso, '120.00']] as const) {
    const criada = await ctxAna.request.post(`${API}/workspaces/${ws.id}/transactions/`, {
      data: {
        title: `Mercado ${quando.slice(0, 7)}`,
        total_amount: valor,
        transaction_date: quando,
        payment_method: 'pix',
        settled: true,
        payers: [{ user_id: eu.id, amount: valor }],
        splits: [
          { user_id: eu.id, split_method: 'equal', input_value: '0' },
          { user_id: outro.id, split_method: 'equal', input_value: '0' },
        ],
      },
    });
    expect(criada.ok(), await criada.text()).toBeTruthy();
  }
  void diaLocal;

  const page = await ctxAna.newPage();
  await page.goto('/me/settlements');
  await page.waitForLoadState('networkidle');

  // --- 1. Os DOIS meses aparecem como origem do saldo ----------------------
  // A seção nasce RECOLHIDA (são N espaços na mesma página): sem abrir, os
  // valores existem no DOM e estão escondidos — e um `toHaveCount(0)` depois
  // passaria por eles estarem fechados, não por o mês ter sido quitado.
  const abrirOrigem = async () => {
    const resumo = page.getByText(/De onde vem esse saldo/).first();
    await expect(resumo).toBeVisible();
    if (!(await page.locator('details[open]').count())) await resumo.click();
  };
  await abrirOrigem();
  await expect(page.getByText(/R\$\s*100,00/).first()).toBeVisible();
  await expect(page.getByText(/R\$\s*60,00/).first()).toBeVisible();

  // --- 2. Registra o acerto pelo Resumo ------------------------------------
  // "Recebi" na linha do Bruno: é a Ana olhando, e ela é a credora.
  await page.getByRole('button', { name: 'Recebi' }).first().click();
  const dialogo = page.getByRole('dialog');
  await expect(dialogo).toBeVisible();
  // Só o valor do mês MAIS ANTIGO: o outro tem de sobreviver na tela.
  await dialogo.getByLabel(/valor/i).fill('100,00');
  // A promessa que a pessoa lê antes de confirmar — ela dizia "sem fechar mês
  // nenhum", que era o defeito anunciado em voz alta.
  await expect(dialogo.getByText(/do mais antigo para o mais novo/i)).toBeVisible();
  await dialogo.getByRole('button', { name: 'Registrar' }).click();
  await expect(dialogo).toBeHidden();

  // --- 3. O mês mais antigo SOME; o outro fica ------------------------------
  await page.waitForLoadState('networkidle');
  await abrirOrigem();
  await expect(
    page.getByText(/R\$\s*100,00/),
    'o mês pago continuou devendo depois do acerto — é o defeito relatado',
  ).toHaveCount(0);
  await expect(
    page.getByText(/R\$\s*60,00/).first(),
    'a seção inteira sumiu em vez de o mês fechar — o teste estaria passando pelo motivo errado',
  ).toBeVisible();

  // --- 4. Desfazer, ali mesmo ----------------------------------------------
  await page.getByRole('tab', { name: 'Histórico' }).click();
  await page.getByRole('button', { name: /Desfazer acerto de/ }).first().click();
  const confirmacao = page.getByRole('dialog');
  await confirmacao.getByRole('button', { name: 'Desfazer' }).click();

  // --- 5. E a dívida volta, ao mês de onde saiu ----------------------------
  await page.getByRole('tab', { name: 'Resumo' }).click();
  await page.waitForLoadState('networkidle');
  await abrirOrigem();
  await expect(page.getByText(/R\$\s*100,00/).first()).toBeVisible();

  void antigo.mes; void recente.mes;
  await ctxAna.close();
  await ctxBruno.close();
});
