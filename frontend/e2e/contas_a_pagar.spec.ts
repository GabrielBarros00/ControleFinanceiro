import { test, expect, type BrowserContext } from '@playwright/test';

/**
 * Contas a pagar e a revisão da recorrência, ponta a ponta (ADR 0029 + 0030).
 *
 * As duas coisas que os testes de unidade não conseguem provar juntas:
 *
 * 1. **O boleto do futuro não sai do caixa, e sai quando é pago.** É a promessa
 *    inteira do ADR 0029 atravessando três telas — o formulário, Contas a pagar
 *    e o Seu mês — e o número tem de fechar nas três.
 * 2. **Salvar a recorrência abre a revisão.** O `<select>` invisível que ela
 *    substitui existia e não fazia o que prometia; aqui se verifica que a tela
 *    aparece, lista o lançamento e diz o que vai acontecer com ele.
 */
const API = 'http://localhost:8000/api/v1';

async function conta(browser: { newContext: () => Promise<BrowserContext> }) {
  const ts = Date.now() + Math.floor(Math.random() * 1000);
  const context = await browser.newContext();
  const email = `pagar${ts}@e2e.com`;
  await context.request.post(`${API}/auth/register`, {
    data: { name: 'Pagadora', email, password: 'senha123' },
  });
  await context.request.post(`${API}/auth/login`, {
    data: { email, password: 'senha123' },
  });
  const [ws] = await (await context.request.get(`${API}/workspaces/`)).json();
  await context.request.post(`${API}/auth/onboarding`, {
    data: { workspace_id: ws.id, salary: 5000 },
  });
  return { context, ws };
}

/** `YYYY-MM-DD` de daqui a `dias`, em componentes locais (nunca toISOString). */
function emDias(dias: number): string {
  const d = new Date();
  d.setDate(d.getDate() + dias);
  const mes = String(d.getMonth() + 1).padStart(2, '0');
  return `${d.getFullYear()}-${mes}-${String(d.getDate()).padStart(2, '0')}`;
}

/** Mês corrente em `YYYY-MM`, para o filtro de Contas a pagar. */
function mesCorrente(): string {
  return emDias(0).slice(0, 7);
}

test.describe('Contas a pagar', () => {
  test('o boleto do futuro espera na fila e só vira caixa quando é pago', async ({ browser }) => {
    const { context, ws } = await conta(browser);
    const page = await context.newPage();

    // --- 1. Lança um boleto que vence daqui a alguns dias ------------------
    await page.goto(`/w/${ws.id}`);
    await page.locator('header').getByRole('button', { name: 'Nova despesa' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await dialog.getByLabel('Título / Descrição').fill('Conta de luz');
    await dialog.getByLabel('Valor Total').fill('300,00');

    // Data FUTURA desmarca "Já foi paga" sozinho — ninguém pagou o boleto que
    // vence semana que vem.
    await dialog.getByLabel('Data', { exact: true }).fill(emDias(5));
    await expect(dialog.getByRole('checkbox', { name: /Já foi paga/ })).not.toBeChecked();

    // Volta para hoje (a caixa se remarca) e desmarca À MÃO: "o boleto chegou,
    // ainda não paguei". Manter a despesa no mês CORRENTE é de propósito — com
    // data no mês seguinte, rodar este teste no fim do mês tiraria a conta do
    // recorte que a tela pede, e a falha não seria sobre liquidação nenhuma.
    await dialog.getByLabel('Data', { exact: true }).fill(emDias(0));
    await expect(dialog.getByRole('checkbox', { name: /Já foi paga/ })).toBeChecked();
    await dialog.getByRole('checkbox', { name: /Já foi paga/ }).uncheck();

    await dialog.getByRole('button', { name: 'Salvar Despesa' }).click();
    await expect(dialog).toBeHidden();

    // --- 2. Ela aparece em Contas a pagar, e NÃO no caixa ------------------
    await page.goto(`/me/payables?month=${mesCorrente()}`);
    await expect(page.getByRole('heading', { name: 'Contas a pagar' })).toBeVisible();
    await expect(page.getByText('Conta de luz')).toBeVisible();

    await page.goto('/overview');
    // "Ainda a pagar" é o número que não existia: antes do ADR 0029 toda conta
    // era dada por paga no instante em que era registrada.
    await expect(page.getByText('Ainda a pagar')).toBeVisible();
    // A linha de saída só aparece com valor != 0 — nada saiu do caixa ainda.
    await expect(page.getByText('Lançamentos à vista')).toHaveCount(0);

    // --- 3. Marcar como paga move o dinheiro ------------------------------
    await page.goto(`/me/payables?month=${mesCorrente()}`);
    await page.getByLabel(/Marcar Conta de luz .* como paga/).check();
    await expect(page.getByText('1 conta selecionada')).toBeVisible();
    await page.getByRole('button', { name: 'Marcar como paga' }).click();

    await expect(page.getByText('Nenhuma conta em aberto')).toBeVisible();

    await page.goto('/overview');
    await expect(page.getByText('Lançamentos à vista')).toBeVisible();
    await expect(page.getByText('Ainda a pagar')).toHaveCount(0);

    await context.close();
  });
});

test.describe('Revisão da recorrência', () => {
  test('salvar mostra o que acontece com os lançamentos já criados', async ({ browser }) => {
    const { context, ws } = await conta(browser);

    // A recorrência começa no 1º deste mês para a ocorrência do mês corrente já
    // existir quando a tela abrir (a materialização é preguiçosa).
    const hoje = new Date();
    const primeiro = `${hoje.getFullYear()}-${String(hoje.getMonth() + 1).padStart(2, '0')}-01`;
    await context.request.post(`${API}/workspaces/${ws.id}/recurring`, {
      data: {
        title: 'Aluguel',
        base_amount: '1000.00',
        frequency: 'monthly',
        day_of_month: 1,
        start_date: primeiro,
      },
    });

    const page = await context.newPage();
    // Materializa a ocorrência do mês (rota de leitura).
    await page.goto(`/w/${ws.id}/transactions`);
    await expect(page.getByText('Aluguel').first()).toBeVisible();

    await page.goto(`/w/${ws.id}/recurring`);
    await page.getByRole('button', { name: /Editar recorrência Aluguel/ }).click();
    const form = page.getByRole('dialog');
    await expect(form).toBeVisible();

    // Muda o dia: o caso que NÃO movia nada antes do ADR 0030.
    await form.getByLabel('Dia do mês').fill('20');
    await form.getByRole('button', { name: 'Salvar' }).click();

    // A revisão assume o fluxo: lista o lançamento e diz o que vai acontecer.
    const revisao = page.getByRole('dialog').filter({
      hasText: 'Aplicar a quais lançamentos?',
    });
    await expect(revisao).toBeVisible();
    await expect(revisao.getByText('muda de data')).toBeVisible();

    await revisao.getByRole('button', { name: 'Confirmar' }).click();
    await expect(revisao).toBeHidden();

    // E o lançamento de fato mudou de dia — a verificação que o `<select>`
    // antigo prometia e não entregava.
    const lancamentos = await (
      await context.request.get(`${API}/workspaces/${ws.id}/transactions/?limit=50`)
    ).json();
    const aluguel = lancamentos.items.find((t: { title: string }) => t.title === 'Aluguel');
    expect(aluguel.occurrence_date ?? aluguel.transaction_date).toContain('-20');

    await context.close();
  });
});
