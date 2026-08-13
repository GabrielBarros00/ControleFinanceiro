import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';

/**
 * NÃO é um teste de verdade — é um roteiro de captura de telas para o estudo de
 * redesign do frontend. Semeia dados realistas via API (APIRequestContext não
 * envia header Origin, então passa pelo middleware CSRF) e navega por todas as
 * rotas capturando screenshots em tema claro e escuro.
 *
 * Rodar isolado:  npx playwright test zz_screenshots.spec.ts
 * Saída:          frontend/screenshots/*.png
 */

// baseURL sem path: paths absolutos (/api/v1/...) resolvem certo no new URL().
const HOST = 'http://localhost:8000';
const u = (p: string) => `${HOST}/api/v1${p}`;
const SHOTS = path.join(process.cwd(), 'screenshots');
// E-mail FIXO, e igual ao `SUPERADMIN_EMAIL` que a config passa ao servidor: é
// o que faz esta conta nascer superadministradora pela janela de bootstrap
// (ADR 0026) e, com isso, alcançar `/admin` — a única tela do site que um
// usuário comum não vê. Com e-mail sorteado por timestamp ela nunca casaria com
// o `SUPERADMIN_EMAIL`, e a área administrativa ficaria fora do catálogo.
//
// Ser fixo significa que a conta sobrevive entre execuções; por isso o cadastro
// abaixo tolera "já existe" e cai no login, e a semeadura só roda em banco
// vazio. Mesmo padrão do `scripts/smoke_prod.py`, pela mesma razão: o roteiro
// precisa ser repetível.
const email = 'demo@cf4.app';
const password = 'password123';
const name = 'Ana Martins';

function iso(daysAgo: number): string {
  const d = new Date();
  d.setDate(d.getDate() - daysAgo);
  d.setHours(12, 0, 0, 0);
  return d.toISOString();
}

// Telas PÚBLICAS. Capturadas nos dois temas: são a primeira coisa que alguém vê
// e, até esta rodada, só existiam em claro no catálogo.
const AUTH_ROUTES: Array<{ path: string; slug: string }> = [
  { path: '/login', slug: 'auth-login' },
  { path: '/register', slug: 'auth-register' },
  { path: '/forgot-password', slug: 'auth-esqueci-senha' },
  // Sem token válido a tela se mostra no estado de link inválido — que é
  // justamente o estado que alguém encontra ao clicar num link vencido.
  { path: '/reset-password', slug: 'auth-redefinir-senha' },
];

/**
 * Rotas autenticadas, com os caminhos CANÔNICOS.
 *
 * Antes esta lista usava `/income`, `/cards`, `/transactions`… que hoje são
 * apenas redirecionamentos legados mantidos para quem tinha URL salva. Funcionava
 * por acidente: no dia em que esses aliases saírem, metade do catálogo passaria a
 * fotografar a mesma tela de Início sem ninguém perceber — as capturas continuam
 * "verdes" porque ninguém as confere.
 *
 * As três seções seguem os eixos do produto: pessoal (ADR 0021), colaboração e
 * plataforma (ADR 0026).
 */
const appRoutes = (wsId: number): Array<{ path: string; slug: string }> => [
  // --- Pessoal: o que é da pessoa e a acompanha ---
  { path: '/overview', slug: 'inicio-global' },
  { path: '/me/income', slug: 'rendas' },
  { path: '/me/cards', slug: 'cartoes' },
  { path: '/me/financing', slug: 'financiamentos' },
  { path: '/me/commitments', slug: 'compromissos' },
  { path: '/me/reports', slug: 'meus-relatorios' },
  { path: '/me/ledger', slug: 'extrato' },
  { path: '/me/settings', slug: 'configuracoes-pessoais' },
  // --- Colaboração: o workspace ---
  { path: `/w/${wsId}`, slug: 'painel-workspace' },
  { path: `/w/${wsId}/transactions`, slug: 'lancamentos' },
  { path: `/w/${wsId}/reports`, slug: 'relatorios' },
  { path: `/w/${wsId}/recurring`, slug: 'recorrencia' },
  { path: `/w/${wsId}/debts`, slug: 'acertos' },
  { path: `/w/${wsId}/import`, slug: 'importar' },
  { path: `/w/${wsId}/settings`, slug: 'configuracoes-workspace' },
  // --- Plataforma: quem opera o site ---
  { path: '/admin', slug: 'administracao' },
];

test('seed data and capture all screens', async ({ page, playwright }) => {
  test.setTimeout(300_000);
  fs.mkdirSync(SHOTS, { recursive: true });

  // ------------------------------------------------------------------ SEED
  const api = await playwright.request.newContext();

  // 400 = a conta sobrou de uma execução anterior contra o mesmo `shots.db`.
  // Não é erro: o roteiro segue pelo login. Só o 403 seria fatal, e ele
  // significaria que o `REGISTRATION_MODE=open` da config não chegou ao servidor.
  const reg = await api.post(u('/auth/register'), { data: { name, email, password } });
  expect(
    reg.ok() || reg.status() === 400,
    `register: ${reg.status()} ${await reg.text()}`,
  ).toBeTruthy();

  const login = await api.post(u('/auth/login'), { data: { email, password } });
  expect(login.ok(), `login: ${await login.text()}`).toBeTruthy();
  const eu = await (await api.get(u('/auth/me'))).json();
  const uid: number = eu.id;

  // A área administrativa só existe para quem opera o site. Se esta conta não
  // nasceu superadministradora, o `SUPERADMIN_EMAIL` do servidor não bate com o
  // e-mail acima — e a captura de `/admin` sairia como uma tela de erro, sem que
  // ninguém notasse ao olhar o catálogo.
  expect(
    eu.platform_role,
    'a conta do roteiro precisa ser superadmin para capturar /admin — confira o SUPERADMIN_EMAIL em playwright.shots.config.ts',
  ).toBe('superadmin');

  const wss = await (await api.get(u('/workspaces/'))).json();
  const wsId: number = wss[0].id;

  // Semeadura só em banco vazio: rodando de novo sobre o mesmo `shots.db`, os
  // lançamentos dobrariam a cada execução e as telas mudariam de conteúdo sem
  // que nada no produto tivesse mudado.
  const jaTemDados =
    ((await (await api.get(u(`/workspaces/${wsId}/transactions/?limit=1&page=1`))).json())?.items
      ?.length ?? 0) > 0;

  const cats: { id: number; name: string }[] = await (await api.get(u(`/workspaces/${wsId}/categories`))).json();
  const catId = (n: string): number | undefined => cats.find((c) => c.name === n)?.id;

  if (!jaTemDados) {
    // Rendas — em `/me/income`, não em `/workspaces/{id}/income`.
    //
    // O caminho antigo saiu no ADR 0021, quando renda virou pessoal, e este
    // roteiro continuou postando lá: as chamadas falhavam em silêncio, porque
    // ninguém conferia a resposta. O efeito aparecia em TODAS as capturas —
    // "Renda R$ 0,00" no Início, "Nenhuma renda registrada" na tela de Rendas —
    // e passava por estado legítimo do app em vez de defeito do roteiro.
    //
    // Daí o `expect`: semeadura que falha tem de derrubar a captura, não gerar
    // um catálogo de telas vazias.
    for (const renda of [
      // Valores GRANDES e títulos LONGOS de propósito: o catálogo existe para
      // mostrar a interface sob carga real, e é com sete dígitos e nome comprido
      // que aparece truncamento, quebra de coluna e número espremido. Dado
      // pequeno esconde exatamente o defeito que a captura deveria revelar.
      { title: 'Salário — Consultoria Internacional de Tecnologia Ltda.', amount: 187_450.9, received_at: iso(6) },
      { title: 'Participação nos Lucros e Resultados (PLR anual)', amount: 1_284_390.55, received_at: iso(9) },
      { title: 'Freelance Design', amount: 1850, received_at: iso(3) },
    ]) {
      const res = await api.post(u('/me/income/'), { data: renda });
      expect(res.ok(), `renda "${renda.title}": ${res.status()} ${await res.text()}`).toBeTruthy();
    }

    // Despesas (bulk) — títulos e valores realistas, espalhados no mês
    const txs = [
      { title: 'Supermercado Pão de Açúcar', total_amount: 435.9, transaction_date: iso(2), cat: 'Mercado' },
      { title: 'Aluguel Apartamento', total_amount: 2100, transaction_date: iso(18), cat: 'Moradia' },
      { title: 'Conta de Luz', total_amount: 187.42, transaction_date: iso(15), cat: 'Moradia' },
      { title: 'Uber para o trabalho', total_amount: 32.8, transaction_date: iso(1), cat: 'Transporte' },
      { title: 'Farmácia Drogasil', total_amount: 76.3, transaction_date: iso(6), cat: 'Saúde' },
      { title: 'Cinema Iguatemi', total_amount: 90, transaction_date: iso(4), cat: 'Lazer' },
      { title: 'Curso de Inglês', total_amount: 320, transaction_date: iso(12), cat: 'Educação' },
      { title: 'Netflix', total_amount: 55.9, transaction_date: iso(10), cat: 'Assinaturas' },
      { title: 'Spotify', total_amount: 21.9, transaction_date: iso(10), cat: 'Assinaturas' },
      { title: 'Restaurante Japonês', total_amount: 148.5, transaction_date: iso(3), cat: 'Alimentação' },
      { title: 'Padaria', total_amount: 28.4, transaction_date: iso(0), cat: 'Alimentação' },
      { title: 'Gasolina', total_amount: 250, transaction_date: iso(7), cat: 'Transporte' },
      { title: 'Presente Aniversário', total_amount: 120, transaction_date: iso(5), cat: 'Outros' },
      // Casos-limite: valor de sete dígitos e descrição que não cabe na coluna.
      { title: 'Reforma completa do apartamento — mão de obra, material e projeto de arquitetura', total_amount: 1_487_632.41, transaction_date: iso(14), cat: 'Moradia' },
      { title: 'Matrícula e mensalidade anual da escola bilíngue das crianças', total_amount: 94_800, transaction_date: iso(11), cat: 'Educação' },
      { title: 'Centavo', total_amount: 0.01, transaction_date: iso(1), cat: 'Outros' },
    ];
    await api.post(u(`/workspaces/${wsId}/transactions/bulk`), {
      data: txs.map((t) => ({ title: t.title, total_amount: t.total_amount, transaction_date: t.transaction_date })),
    });

    // Atribui categoria (item único) a cada despesa recém-criada
    const list = await (await api.get(u(`/workspaces/${wsId}/transactions/?limit=100&page=1`))).json();
    for (const item of list.items) {
      const seed = txs.find((t) => t.title === item.title);
      const cid = seed?.cat ? catId(seed.cat) : undefined;
      if (cid) {
        await api.put(u(`/workspaces/${wsId}/transactions/${item.id}`), { data: { category_id: cid } });
      }
    }

    // Cartão de crédito — em `/me/credit-cards`, NÃO em `/workspaces/{id}/...`.
    //
    // Mesmo defeito das rendas: o caminho antigo saiu no ADR 0021 e o roteiro
    // continuou postando lá sem conferir a resposta. A tela de Cartões saía com
    // "Nenhum cartão cadastrado" no catálogo inteiro — e, como é um estado
    // legítimo do app, ninguém desconfiava.
    const cardRes = await api.post(u('/me/credit-cards/'), {
      data: {
        name: 'Cartão Platinum Internacional — Banco do Brasil',
        limit: 250_000,
        closing_day: 28,
        due_day: 7,
      },
    });
    expect(cardRes.ok(), `cartão: ${cardRes.status()} ${await cardRes.text()}`).toBeTruthy();
    const card = await cardRes.json();
    const charges = [
      { title: 'iFood', amount: 68.5 },
      { title: 'Amazon.com.br', amount: 239.9 },
      { title: 'Passagens aéreas internacionais para a família (quatro pessoas)', amount: 78_940.3 },
      { title: 'Zara', amount: 419.9 },
    ];
    for (const c of charges) {
      await api.post(u(`/workspaces/${wsId}/transactions/`), {
        data: {
          title: c.title,
          total_amount: c.amount,
          transaction_date: iso(3),
          payment_method: 'credit_card',
          credit_card_id: card.id,
          split_mode: 'transaction',
          payers: [{ user_id: uid, amount: c.amount }],
          splits: [{ user_id: uid, split_method: 'equal', input_value: 100 }],
        },
      });
    }

    // ---------------------------------------------------------------- ------
    // O que nunca foi semeado, e por isso saía vazio no catálogo: as telas de
    // Financiamentos, Recorrência, Compromissos, Acertos e Orçamento
    // mostravam o estado "nenhum registro" como se fosse a cara do produto.
    // -----------------------------------------------------------------------

    // Financiamento (aparece em Financiamentos e em Compromissos)
    const fin = await api.post(u('/me/financing/'), {
      data: {
        title: 'Financiamento Imobiliário — Apartamento Vila Madalena, 3 dormitórios',
        total_amount: 1_250_000,
        // Fração MENSAL, não porcentagem anual: o modelo documenta `0.01 = 1% a.m.`.
        // Passar 9.75 aqui significa 975% ao mês, e o serviço recusa com razão
        // ("a prestação não cobre nem os juros"). 0.0078 ≈ 9,75% ao ano.
        interest_rate: 0.0078,
        start_date: iso(400).slice(0, 10),
        installments_count: 360,
        method: 'PRICE',
      },
    });
    expect(fin.ok(), `financiamento: ${fin.status()} ${await fin.text()}`).toBeTruthy();

    // Conta de pagamento (origem do dinheiro nos lançamentos)
    const conta = await api.post(u('/me/payment-accounts/'), {
      data: { name: 'Conta Corrente Itaú Personnalité — Agência 0912', type: 'checking' },
    });
    expect(conta.ok(), `conta: ${conta.status()} ${await conta.text()}`).toBeTruthy();

    // Despesa recorrente (tela de Recorrência)
    for (const rec of [
      { title: 'Aluguel do apartamento com condomínio e IPTU incluídos', base_amount: 8_450.75, frequency: 'monthly', day_of_month: 5 },
      { title: 'Plano de saúde familiar', base_amount: 3_280.4, frequency: 'monthly', day_of_month: 12 },
    ]) {
      const r = await api.post(u(`/workspaces/${wsId}/recurring`), { data: rec });
      expect(r.ok(), `recorrência "${rec.title}": ${r.status()} ${await r.text()}`).toBeTruthy();
    }

    // Renda recorrente (segunda tabela da tela de Rendas)
    const recIncome = await api.post(u('/me/recurring-income/'), {
      data: { title: 'Salário mensal líquido', base_amount: 187_450.9, frequency: 'monthly', day_of_month: 5 },
    });
    expect(recIncome.ok(), `renda recorrente: ${recIncome.status()} ${await recIncome.text()}`).toBeTruthy();

    // Orçamento por categoria (aba Orçamento em Relatórios)
    const mesAtual = new Date().toISOString().slice(0, 7);
    for (const orc of [
      { category: 'Moradia', amount: 12_000, month: mesAtual },
      { category: 'Alimentação', amount: 4_500, month: mesAtual },
      { category: 'Transporte', amount: 2_800, month: mesAtual },
    ]) {
      const r = await api.post(u(`/workspaces/${wsId}/analytics/estimates`), { data: orc });
      expect(r.ok(), `orçamento "${orc.category}": ${r.status()} ${await r.text()}`).toBeTruthy();
    }

    // Segunda pessoa no workspace. Sem ela a tela de Acertos não tem o que
    // mostrar: dívida entre pessoas pressupõe divisão, e com um único usuário o
    // saldo é sempre zero — era por isso que "Acertos" aparecia vazia no
    // catálogo, sem que nada estivesse errado.
    const apiB = await playwright.request.newContext();
    const emailB = 'bruno.demo@cf4.app';
    await apiB.post(u('/auth/register'), {
      data: { name: 'Bruno Nascimento Albuquerque', email: emailB, password },
    });
    const loginB = await apiB.post(u('/auth/login'), { data: { email: emailB, password } });
    expect(loginB.ok(), `login de Bruno: ${await loginB.text()}`).toBeTruthy();
    const bruno = await (await apiB.get(u('/auth/me'))).json();

    const convite = await api.post(u(`/workspaces/${wsId}/invites`), {
      data: { email: emailB, role: 'member' },
    });
    expect(convite.ok(), `convite: ${convite.status()} ${await convite.text()}`).toBeTruthy();
    const avisos = await (await apiB.get(u('/notifications'))).json();
    const token = avisos.items.find((n: { invite_token?: string }) => n.invite_token)?.invite_token;
    expect(token, 'Bruno recebeu o convite').toBeTruthy();
    expect((await apiB.post(u(`/invites/accept/${token}`))).ok()).toBeTruthy();

    // Despesas rateadas: é o que gera saldo devedor entre as duas pessoas.
    for (const d of [
      { title: 'Jantar de comemoração no restaurante do hotel', total: 3_890.6 },
      { title: 'Viagem de fim de ano — hospedagem e passagens', total: 214_500 },
    ]) {
      const r = await api.post(u(`/workspaces/${wsId}/transactions/`), {
        data: {
          title: d.title,
          total_amount: d.total,
          transaction_date: iso(4),
          payers: [{ user_id: uid, amount: d.total }],
          splits: [
            { user_id: uid, split_method: 'equal', input_value: 0 },
            { user_id: bruno.id, split_method: 'equal', input_value: 0 },
          ],
        },
      });
      expect(r.ok(), `despesa rateada "${d.title}": ${r.status()} ${await r.text()}`).toBeTruthy();
    }
    await apiB.dispose();
  }

  // ----------------------------------------------------------- SCREENSHOTS
  await page.setViewportSize({ width: 1440, height: 900 });

  // Sempre injeta o workspace atual (persist do zustand) antes do app carregar.
  // NÃO mexe no theme aqui — o theme é controlado por evaluate+reload por fase.
  await page.addInitScript((ws) => {
    localStorage.setItem('cf4-ui', JSON.stringify({ state: { currentWorkspaceId: ws }, version: 0 }));
  }, wsId);

  const shot = async (slug: string) => {
    await page.screenshot({ path: path.join(SHOTS, `${slug}.png`), fullPage: true });
  };

  const settle = async () => {
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.waitForTimeout(900); // deixa as animações fade-in/framer terminarem
  };

  // ---- Público, nos DOIS temas ----
  // O tema mora no localStorage e é lido na carga; por isso grava-se antes de
  // navegar. Estas telas são as únicas que alguém vê deslogado, e o catálogo
  // não tinha a versão escura de nenhuma delas.
  const capturarPublicas = async (theme: 'light' | 'dark') => {
    await page.goto('/login');
    await page.evaluate((t) => localStorage.setItem('theme', t), theme);
    for (const r of AUTH_ROUTES) {
      await page.goto(r.path);
      await page.reload();
      await settle();
      await shot(`${r.slug}-${theme}`);
    }
  };
  await capturarPublicas('light');
  await capturarPublicas('dark');

  // ---- Login pela UI (garante cookie no contexto do browser) ----
  await page.goto('/login');
  await page.getByLabel('E-mail').fill(email);
  await page.getByLabel('Senha', { exact: true }).fill(password);
  await page.getByRole('button', { name: /Acessar Conta/ }).first().click();
  await page.waitForURL('**/');
  await settle();

  // Onboarding aparece para needs_onboarding=true
  await shot('onboarding-modal');

  // Encerra o onboarding via API (flip do flag, sem criar renda/cartão) e recarrega
  await api.post(u('/auth/onboarding'), { data: { workspace_id: wsId, salary: 0 } });

  const captureAll = async (theme: 'light' | 'dark') => {
    // aplica o theme e recarrega (addInitScript re-seta só o workspace)
    await page.goto('/');
    await page.evaluate((t) => localStorage.setItem('theme', t), theme);
    await page.reload();
    await settle();

    for (const r of appRoutes(wsId)) {
      await page.goto(r.path);
      await settle();
      await shot(`${r.slug}-${theme}`);
    }

    // Modal Nova Despesa (a partir do painel do workspace)
    await page.goto(`/w/${wsId}`);
    await settle();
    const novaBtn = page.getByRole('button', { name: 'Nova Despesa' });
    if (await novaBtn.count()) {
      await novaBtn.first().click();
      await page.getByRole('dialog').waitFor({ state: 'visible' }).catch(() => {});
      await page.waitForTimeout(600);
      await shot(`nova-despesa-modal-${theme}`);
      await page.keyboard.press('Escape').catch(() => {});
    }

    // Modal Nova Renda — verifica o switch "Renda recorrente" (contraste OFF/ON)
    // e o campo "Começa em" do editor de recorrência.
    await page.goto('/me/income');
    await settle();
    const novaRenda = page.getByRole('button', { name: /Nova renda/i });
    if (await novaRenda.count()) {
      await novaRenda.first().click();
      await page.getByRole('dialog').waitFor({ state: 'visible' }).catch(() => {});
      await page.waitForTimeout(500);
      await shot(`nova-renda-modal-off-${theme}`);
      const sw = page.getByRole('switch');
      if (await sw.count()) {
        await sw.first().click();
        await page.waitForTimeout(500);
        await shot(`nova-renda-modal-on-${theme}`);
      }
      await page.keyboard.press('Escape').catch(() => {});
    }
  };

  await captureAll('light');
  await captureAll('dark');

  // ---- Mobile (bottom-nav + responsivo), nos DOIS temas ----
  await page.setViewportSize({ width: 390, height: 844 });
  const capturarMobile = async (theme: 'light' | 'dark') => {
    await page.goto('/overview');
    await page.evaluate((t) => localStorage.setItem('theme', t), theme);
    await page.reload();
    await settle();
    for (const r of [
      { path: '/overview', slug: 'inicio' },
      { path: `/w/${wsId}/transactions`, slug: 'lancamentos' },
      { path: `/w/${wsId}/reports`, slug: 'relatorios' },
      { path: '/me/cards', slug: 'cartoes' },
    ]) {
      await page.goto(r.path);
      await settle();
      await shot(`mobile-${r.slug}-${theme}`);
    }
  };
  await capturarMobile('light');
  await capturarMobile('dark');

  console.log(`\n>>> Screenshots salvos em: ${SHOTS}\n`);
});
