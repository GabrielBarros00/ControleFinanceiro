import { test, expect, type BrowserContext, type Page } from '@playwright/test';

const API = 'http://localhost:8000/api/v1';

/**
 * Acertos ponta a ponta — a conta tem de fechar NA TELA (ADR 0031).
 *
 * A identidade `saldo acumulado = Σ meses + o que não tem mês` está travada em
 * teste de unidade no `DebtService`, e a renderização está travada em vitest com
 * dados de mentira. O que faltava é o meio: a rota, a serialização em string
 * decimal, o hook, o componente e o `Intl` do navegador — a cadeia inteira num
 * cenário em que os dois tipos de acerto existem.
 *
 * O cenário é montado para que os três termos sejam DIFERENTES entre si. Com
 * números iguais, um erro de troca de linha passaria despercebido.
 */
const ts = Date.now();
const ana = { name: 'Ana Acerto', email: `ana.acerto${ts}@e2e.com`, password: 'senha123' };
const bruno = { name: 'Bruno Acerto', email: `bruno.acerto${ts}@e2e.com`, password: 'senha123' };

async function registrar(context: BrowserContext, user: typeof ana) {
  expect((await context.request.post(`${API}/auth/register`, { data: user })).ok()).toBeTruthy();
  expect(
    (await context.request.post(`${API}/auth/login`, {
      data: { email: user.email, password: user.password },
    })).ok(),
  ).toBeTruthy();
}

/** Primeiro dia do mês, `delta` meses atrás — ancorado ao meio-dia para o
 *  `billing_month` não escorregar de mês por fuso (ADR 0025). */
function mesAtras(delta: number): { iso: string; mes: string } {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - delta);
  d.setHours(12, 0, 0, 0);
  const mes = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  return { iso: d.toISOString(), mes };
}

/** "R$ 1.234,56" → 1234.56 */
function paraNumero(texto: string): number {
  const m = texto.match(/R\$\s*([\d.]+,\d{2})/);
  expect(m, `sem valor em "${texto}"`).toBeTruthy();
  return reais(m![1]);
}

function reais(bruto: string): number {
  return Number(bruto.replace(/\./g, '').replace(',', '.'));
}

/**
 * O saldo que a linha DECLARA, com sinal.
 *
 * Ancorado na frase de direção, não no primeiro `R$` do texto: a linha de um mês
 * parcialmente acertado carrega DOIS valores ("R$ 120,00 já acertados" e "você
 * deve R$ 180,00"), e pegar o primeiro fazia o teste somar o acerto no lugar do
 * saldo — dando −170 onde a tela mostrava −230. O app estava certo; a leitura é
 * que era ambígua, e é a mesma ambiguidade que um olho apressado teria.
 */
function comSinal(texto: string): number {
  const m = texto.match(/você (deve|recebe) R\$\s*([\d.]+,\d{2})/);
  expect(m, `frase sem direção em "${texto}"`).toBeTruthy();
  const valor = reais(m![2]);
  return m![1] === 'deve' ? -valor : valor;
}

async function linhasDaOrigem(page: Page): Promise<number[]> {
  const bloco = page.locator('h2', { hasText: /De onde vem esse saldo|Meses ainda não fechados/ })
    .locator('xpath=../..');
  const linhas = bloco.locator('li');
  const total = await linhas.count();
  const valores: number[] = [];
  for (let i = 0; i < total; i++) {
    valores.push(comSinal((await linhas.nth(i).innerText()).replace(/\n/g, ' ')));
  }
  return valores;
}

test.describe('Acertos — a origem do saldo fecha na tela', () => {
  test('os meses somam o acumulado, e o acerto sem mês aparece como linha', async ({ browser }) => {
    test.setTimeout(180_000);

    const ctxAna = await browser.newContext();
    const ctxBruno = await browser.newContext();
    await registrar(ctxAna, ana);
    await registrar(ctxBruno, bruno);

    const [ws] = await (await ctxAna.request.get(`${API}/workspaces/`)).json();
    await ctxAna.request.post(`${API}/auth/onboarding`, { data: { workspace_id: ws.id, salary: 5000 } });
    const [wsB] = await (await ctxBruno.request.get(`${API}/workspaces/`)).json();
    await ctxBruno.request.post(`${API}/auth/onboarding`, { data: { workspace_id: wsB.id, salary: 5000 } });

    // Bruno entra no espaço da Ana. O convite não adiciona ninguém sozinho —
    // quem já tem conta precisa aceitar (consentimento no convite).
    const convite = await ctxAna.request.post(`${API}/workspaces/${ws.id}/invites`, {
      data: { email: bruno.email, role: 'member' },
    });
    expect(convite.ok(), await convite.text()).toBeTruthy();
    const avisos = await (await ctxBruno.request.get(`${API}/notifications`)).json();
    const token = avisos.items.find((n: { invite_token?: string }) => n.invite_token)?.invite_token;
    expect(token, 'Bruno recebeu o convite').toBeTruthy();
    expect((await ctxBruno.request.post(`${API}/invites/accept/${token}`)).ok()).toBeTruthy();

    const eu = await (await ctxAna.request.get(`${API}/auth/me`)).json();
    const outro = await (await ctxBruno.request.get(`${API}/auth/me`)).json();

    /*
     * Bruno adianta as duas despesas e a Ana consome metade. Valores diferentes
     * por mês de propósito: se os dois fossem iguais, trocar as linhas de lugar
     * não mudaria a soma e o teste não veria o erro.
     *
     *   mês retrasado: Ana deve 300     (parcialmente acertado abaixo)
     *   mês passado:   Ana deve 100
     */
    const retrasado = mesAtras(2);
    const passado = mesAtras(1);
    for (const [quando, valor] of [[retrasado, '600.00'], [passado, '200.00']] as const) {
      const metade = (Number(valor) / 2).toFixed(2);
      const resp = await ctxBruno.request.post(`${API}/workspaces/${ws.id}/transactions/`, {
        data: {
          title: `Mercado ${quando.mes}`,
          total_amount: valor,
          transaction_date: quando.iso,
          payment_method: 'pix',
          payers: [{ user_id: outro.id, amount: valor }],
          splits: [
            { user_id: eu.id, split_method: 'fixed', input_value: metade },
            { user_id: outro.id, split_method: 'fixed', input_value: metade },
          ],
        },
      });
      expect(resp.ok(), `semear ${quando.mes}: ${await resp.text()}`).toBeTruthy();
    }

    // Acerto COM mês: quita 120 do mês retrasado (sobram 180 lá).
    const comMes = await ctxAna.request.post(`${API}/workspaces/${ws.id}/settlements`, {
      data: {
        from_user_id: eu.id, to_user_id: outro.id,
        amount: '120.00', billing_month: retrasado.mes, note: 'parcial',
      },
    });
    expect(comMes.ok(), await comMes.text()).toBeTruthy();

    // Acerto SEM mês: abate 50 do acumulado e não fecha mês nenhum. É o tipo que
    // era indistinguível do outro antes do ADR 0031.
    const semMes = await ctxAna.request.post(`${API}/workspaces/${ws.id}/settlements`, {
      data: { from_user_id: eu.id, to_user_id: outro.id, amount: '50.00' },
    });
    expect(semMes.ok(), await semMes.text()).toBeTruthy();

    // Esperado: −180 (retrasado) −100 (passado) +50 (sem mês) = −230
    const page = await ctxAna.newPage();
    await page.goto(`/w/${ws.id}/debts`);
    // `exact`: "Como os acertos funcionam?" também é heading nesta aba.
    await expect(page.getByRole('heading', { name: 'Acertos', exact: true })).toBeVisible();

    // --- O topo ---
    await expect(page.getByText('Você deve, no total')).toBeVisible();
    const topo = paraNumero(await page.locator('p.text-2xl').first().innerText());
    expect(topo).toBe(230);

    // --- A quebra fecha ---
    const linhas = await linhasDaOrigem(page);
    expect(linhas.length, 'duas linhas de mês + a de acerto sem mês').toBe(3);
    expect(linhas).toContain(-180);
    expect(linhas).toContain(-100);
    expect(linhas).toContain(50);

    const totalDaQuebra = await page
      .getByText('Total acumulado')
      .locator('xpath=..')
      .innerText();
    expect(comSinal(totalDaQuebra.replace(/\n/g, ' '))).toBe(-230);
    // A soma das linhas exibidas É o total exibido. É a promessa do bloco.
    expect(linhas.reduce((a, b) => a + b, 0)).toBe(-230);

    await expect(page.getByText('Acertos sem mês')).toBeVisible();

    // --- Clicar num mês abre a aba dele, com o mesmo número ---
    await page.getByText('Total acumulado').waitFor();
    const linhaDoRetrasado = page.locator('button', { hasText: 'R$ 180,00' }).first();
    await linhaDoRetrasado.click();
    await expect(page.getByRole('tab', { name: 'Por mês' })).toHaveAttribute('data-state', 'active');
    await expect(page.getByText('Quem deve a quem neste mês')).toBeVisible();
    // `\s` e nunca espaço literal: o `Intl` do pt-BR separa "R$" do número com
    // ESPAÇO NÃO-QUEBRÁVEL (U+00A0), e um espaço comum no padrão não casa.
    await expect(page.getByText(/deve\s+R\$\s*180,00/).first()).toBeVisible();
    // O mês diz quanto já foi acertado — sem repetir a lista de acertos, que
    // vive no Histórico.
    await expect(page.getByText('R$ 120,00 já acertados')).toBeVisible();

    // --- O histórico distingue os dois tipos ---
    await page.getByRole('tab', { name: 'Histórico' }).click();
    await expect(page.getByText('sem mês')).toBeVisible();
    const mesCurto = new Date(`${retrasado.mes}-15T12:00:00`)
      .toLocaleDateString('pt-BR', { month: 'short' })
      .replace('.', '');
    await expect(page.getByText(`${mesCurto}/${retrasado.mes.slice(0, 4)}`)).toBeVisible();

    await ctxAna.close();
    await ctxBruno.close();
  });
});
