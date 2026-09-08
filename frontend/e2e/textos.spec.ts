import { test, expect, type Page, type Browser } from '@playwright/test';
import { diaLocal } from '../e2e-shared/datas';

/*
 * O portão contra o texto que vazou do banco para a tela.
 *
 * Achado da auditoria: em Contas, embaixo do saldo, lia-se **"Conta corrente ·
 * BRL · desde 2026-07-06"**. `2026-07-06` é como a data viaja na API; não é como
 * ninguém escreve uma data em português. O defeito é pequeno e é *invisível para
 * todo teste que o projeto tem*: a página renderiza, o valor está certo, o
 * `scrollWidth` não estoura, o axe não reclama. Só um olho humano — ou este
 * arquivo — vê que a tela está falando o idioma do backend.
 *
 * A varredura é por ROTA e não por componente de propósito. Um teste unitário
 * teria trancado `AccountsPage`, e no mês seguinte a mesma data crua apareceria
 * em Financiamentos. O que se quer garantir não é "esta tela está certa": é
 * *nenhuma tela mostra o formato do banco*.
 *
 * ## O que conta como vazamento
 *
 * - `2026-07-06` — data ISO;
 * - `2026-07-06T12:00:00` — instante ISO;
 * - `PIX`, `CREDIT_CARD` — o valor do enum, em caixa alta, sem tradução.
 *
 * Os três têm a mesma causa (interpolar o campo direto no JSX) e o mesmo efeito
 * (a pessoa lê um identificador em vez de uma informação).
 */
const API = 'http://localhost:8000/api/v1';

/** Data ISO solta no texto: `2026-07-06`, com ou sem hora colada. */
const DATA_CRUA = /\b\d{4}-\d{2}-\d{2}(T[\d:.]+)?\b/;

/**
 * Enum cru: caixa alta com `_` no meio, ou uma das chaves conhecidas da API.
 *
 * O `_` é o que distingue `CREDIT_CARD` de `CPF`, `PIX` e de qualquer sigla
 * legítima — e `PIX`/`DEBIT` entram nomeados porque são os que o projeto de fato
 * expõe. Uma lista fechada erra menos que um padrão esperto: siglas em caixa alta
 * são comuns em interface ("CPF", "BRL", "USD"), e um padrão genérico
 * transformaria este portão numa fonte de ruído — que é como um portão morre.
 */
const ENUM_CRU = /\b(CREDIT_CARD|DEBIT_CARD|BANK_SLIP|PAYMENT_ACCOUNT|CHECKING|SAVINGS|[A-Z]{3,}_[A-Z_]{2,})\b/;

async function contaSemeada(browser: Browser) {
  const ts = Date.now() + Math.floor(Math.random() * 1000);
  const email = `texto${ts}@e2e.com`;
  const context = await browser.newContext({ viewport: { width: 1366, height: 900 } });
  const api = context.request;

  await api.post(`${API}/auth/register`, { data: { name: 'Rui Textos', email, password: 'senha123' } });
  await api.post(`${API}/auth/login`, { data: { email, password: 'senha123' } });
  await api.post(`${API}/auth/onboarding`, { data: { salary: 7000 } });
  const [ws] = await (await api.get(`${API}/workspaces/`)).json();
  const eu = await (await api.get(`${API}/auth/me`)).json();

  // Conta COM saldo de abertura: é o `opening_on` que virava "desde 2026-07-06".
  // Sem a abertura, a linha do defeito nem existe — e o portão nasceria verde
  // por falta de dado, que é o modo mais silencioso de não testar nada.
  const conta = await (await api.post(`${API}/me/payment-accounts`, {
    data: { name: 'Conta Corrente', type: 'checking' },
  })).json();
  await api.put(`${API}/me/payment-accounts/${conta.id}/opening-balance`, {
    data: { amount: '5000.00', as_of: diaLocal() },
  });

  await api.post(`${API}/workspaces/${ws.id}/transactions/`, {
    data: {
      title: 'Mercado',
      total_amount: '220.00',
      transaction_date: new Date().toISOString(),
      payment_method: 'pix',
      settled: false,
      payers: [{ user_id: eu.id, amount: '220.00' }],
      splits: [{ user_id: eu.id, split_method: 'equal', input_value: '0' }],
    },
  });

  return { context, wsId: ws.id as number };
}

/** O texto visível da tela — sem `<script>`, sem `aria-*`, sem atributo. */
async function textoVisivel(page: Page) {
  return page.evaluate(() => {
    const raiz = document.querySelector('main') ?? document.body;
    const linhas: string[] = [];
    const it = document.createTreeWalker(raiz, NodeFilter.SHOW_TEXT);
    let no = it.nextNode();
    while (no) {
      const pai = no.parentElement;
      const texto = (no.textContent ?? '').trim();
      if (texto && pai && !['SCRIPT', 'STYLE'].includes(pai.tagName)) {
        const r = pai.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) linhas.push(texto);
      }
      no = it.nextNode();
    }
    return linhas;
  });
}

test('nenhuma tela mostra data ou enum no formato da API', async ({ browser }) => {
  test.setTimeout(180_000);
  const { context, wsId } = await contaSemeada(browser);
  const page = await context.newPage();

  const rotas = [
    '/overview', '/me/accounts', '/me/payables', '/me/income', '/me/cards',
    '/me/financing', '/me/reports', '/me/ledger', '/me/commitments',
    '/me/settlements', '/me/settings',
    `/w/${wsId}`, `/w/${wsId}/transactions`, `/w/${wsId}/payables`,
    `/w/${wsId}/reports`, `/w/${wsId}/recurring`, `/w/${wsId}/debts`,
  ];

  const vazamentos: string[] = [];
  for (const rota of rotas) {
    await page.goto(rota);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(300);

    // A tela EXISTE? Sem isto, uma rota quebrada passa por limpa — o projeto já
    // teve um portão verde numa página que só mostrava a tarja de erro do Vite.
    const elementos = await page.locator('main *').count();
    expect(elementos, `${rota}: a tela não renderizou nada`).toBeGreaterThan(3);

    for (const linha of await textoVisivel(page)) {
      const data = linha.match(DATA_CRUA);
      const enumeracao = linha.match(ENUM_CRU);
      if (data) vazamentos.push(`${rota}: data crua "${data[0]}" em "${linha.slice(0, 60)}"`);
      if (enumeracao) vazamentos.push(`${rota}: enum cru "${enumeracao[0]}" em "${linha.slice(0, 60)}"`);
    }
  }

  await context.close();
  expect(
    vazamentos,
    `A tela está falando o idioma do banco em ${vazamentos.length} lugar(es):\n  `
    + [...new Set(vazamentos)].join('\n  '),
  ).toEqual([]);
});
