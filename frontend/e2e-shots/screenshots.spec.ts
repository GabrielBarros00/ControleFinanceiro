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

// Fechamento do primeiro cartão semeado. Vive aqui, e não solto no meio do
// roteiro, porque três lugares dependem dele casar: a semeadura da compra
// deslocada, a data que o formulário digita para o aviso aparecer, e o próprio
// cadastro do cartão.
const FECHAMENTO_DO_CARTAO = 28;

/**
 * Véspera do fechamento do primeiro cartão, no mês corrente — a janela em que o
 * atraso de captura do estabelecimento decide em qual fatura a compra cai.
 *
 * Dia fixo do mês CORRENTE (não "hoje menos N"): o aviso da janela só existe
 * antes do fechamento, e uma data relativa cairia dentro ou fora dele conforme o
 * dia em que o roteiro rodasse — a mesma captura mostraria coisas diferentes em
 * dias diferentes, que é o defeito que um catálogo não pode ter.
 *
 * Meio-dia pelo mesmo motivo do `iso` acima e do `civil_instant` do backend:
 * meia-noite, lida em fuso negativo, é o dia anterior.
 */
const vesperaDoFechamento = (() => {
  const d = new Date();
  d.setDate(FECHAMENTO_DO_CARTAO - 1);
  d.setHours(12, 0, 0, 0);
  return d.toISOString();
})();

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
  // Saldo por conta (ADR 0034). Está no catálogo porque foi a screenshot que
  // revelou o "R$ 0,00" que a tela mostrava embaixo de "saldo não configurado" —
  // um zero apresentado com a confiança de um número certo, que nenhum teste
  // pegou porque nenhum teste olha para duas afirmações lado a lado.
  { path: '/me/accounts', slug: 'contas' },
  { path: '/me/payables', slug: 'contas-a-pagar' },
  { path: '/me/income', slug: 'rendas' },
  { path: '/me/cards', slug: 'cartoes' },
  { path: '/me/financing', slug: 'financiamentos' },
  { path: '/me/commitments', slug: 'compromissos' },
  // Par global de `/w/:id/debts` (ADR 0027). A semeadura já cria a segunda
  // pessoa no workspace justamente para os acertos não saírem vazios.
  { path: '/me/settlements', slug: 'meus-acertos' },
  // As outras duas abas de Acertos (o estado vive em `?tab=`, então cada uma é
  // uma URL). Sem estas linhas o catálogo mostraria só o Resumo, e o retrato do
  // mês e o histórico — que é onde mora a tabela mais larga do app — ficariam
  // de fora de qualquer conferência visual.
  { path: '/me/settlements?tab=mes', slug: 'meus-acertos-mes' },
  { path: '/me/settlements?tab=historico', slug: 'meus-acertos-historico' },
  { path: '/me/reports', slug: 'meus-relatorios' },
  { path: '/me/ledger', slug: 'extrato' },
  { path: '/me/settings', slug: 'configuracoes-pessoais' },
  // --- Colaboração: o workspace ---
  { path: `/w/${wsId}`, slug: 'painel-workspace' },
  { path: `/w/${wsId}/transactions`, slug: 'lancamentos' },
  { path: `/w/${wsId}/payables`, slug: 'contas-a-pagar-espaco' },
  { path: `/w/${wsId}/reports`, slug: 'relatorios' },
  { path: `/w/${wsId}/recurring`, slug: 'recorrencia' },
  { path: `/w/${wsId}/debts`, slug: 'acertos' },
  { path: `/w/${wsId}/debts?tab=mes`, slug: 'acertos-mes' },
  { path: `/w/${wsId}/debts?tab=historico`, slug: 'acertos-historico' },
  { path: `/w/${wsId}/import`, slug: 'importar' },
  { path: `/w/${wsId}/settings`, slug: 'configuracoes-workspace' },
  // --- Plataforma: quem opera o site ---
  { path: '/admin', slug: 'administracao' },
];

test('seed data and capture all screens', async ({ page, playwright }) => {
  // 15 min: os 5 anteriores já estouravam com o catálogo cheio, e o roteiro morria
  // no meio da captura MOBILE — deixando metade das telas do dia anterior no
  // diretório, sem nada avisando que eram antigas. Uma captura pela metade é pior
  // que nenhuma, e isto é geração de artefato, não gate de correção.
  test.setTimeout(900_000);
  /*
   * Apaga as capturas antigas ANTES de capturar.
   *
   * Sem isto, renomear o slug de uma rota deixa o arquivo velho para trás para
   * sempre: `mobile-inicio-light.png` sobreviveu duas semanas depois de a rota
   * virar `inicio-global`, foi recomprimido para `docs/images` junto com as
   * outras, e o catálogo continuou apontando para ele — uma tela de duas
   * semanas atrás publicada como se fosse a atual. Ninguém tinha como notar:
   * o arquivo existe, a imagem abre, e ela é uma tela plausível do aplicativo.
   *
   * Limpar aqui faz o conjunto de PNGs ser, por construção, exatamente o que
   * ESTA execução produziu — e o `comprimir-shots.py`, que copia a pasta
   * inteira, herda a garantia.
   */
  fs.rmSync(SHOTS, { recursive: true, force: true });
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
    // CINCO cartões: a tela os dispõe numa grade, e o comportamento com vários
    // (quebra de linha, cartão selecionado, faixa de limite) só aparece com
    // mais de um. Limites de ordens de grandeza diferentes de propósito — o
    // menor tem quatro dígitos, o maior seis.
    let card: { id: number } | null = null;
    for (const c of [
      { name: 'Cartão Platinum Internacional — Banco do Brasil', limit: 250_000, closing_day: FECHAMENTO_DO_CARTAO, due_day: 7 },
      { name: 'Nubank Ultravioleta', limit: 38_000, closing_day: 15, due_day: 22 },
      { name: 'Itaú Personnalité Mastercard Black', limit: 120_000, closing_day: 5, due_day: 12 },
      { name: 'Cartão da loja de materiais de construção (parcelamento sem juros)', limit: 9_500, closing_day: 20, due_day: 28 },
      { name: 'C6 Carbon', limit: 65_000, closing_day: 10, due_day: 18 },
    ]) {
      const r = await api.post(u('/me/credit-cards/'), { data: c });
      expect(r.ok(), `cartão "${c.name}": ${r.status()} ${await r.text()}`).toBeTruthy();
      card = card ?? (await r.json());
    }
    expect(card, 'o primeiro cartão precisa existir para receber as compras').toBeTruthy();
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
          credit_card_id: card!.id,
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
    // SEIS financiamentos, com variedade de método, prazo, valor e tamanho de
    // nome. A tela os apresenta como uma FAIXA DE BOTÕES com `flex-wrap`, cada
    // um exibindo o título inteiro — é justamente aí que a coleção encontra seu
    // limite: com poucos contratos parece um seletor discreto, com muitos vira
    // uma parede que empurra a tabela para fora da tela. Um item só nunca
    // mostraria isso.
    for (const f of [
      { title: 'Financiamento Imobiliário — Apartamento Vila Madalena, 3 dormitórios', total_amount: 1_250_000, interest_rate: 0.0078, installments_count: 360, method: 'PRICE' },
      { title: 'Consórcio de imóvel contemplado — Casa em Atibaia com piscina e quintal', total_amount: 680_000, interest_rate: 0.0065, installments_count: 240, method: 'SAC' },
      { title: 'Veículo — SUV híbrida', total_amount: 289_900, interest_rate: 0.0142, installments_count: 60, method: 'PRICE' },
      { title: 'Reforma da cozinha', total_amount: 87_400, interest_rate: 0.0189, installments_count: 24, method: 'SAC' },
      { title: 'Empréstimo consignado para quitação de dívidas do cartão de crédito', total_amount: 45_000, interest_rate: 0.0215, installments_count: 36, method: 'PRICE' },
      { title: 'Notebook', total_amount: 12_800, interest_rate: 0.0199, installments_count: 12, method: 'PRICE' },
    ]) {
      const r = await api.post(u('/me/financing/'), {
        data: { ...f, start_date: iso(400).slice(0, 10) },
      });
      expect(r.ok(), `financiamento "${f.title}": ${r.status()} ${await r.text()}`).toBeTruthy();
    }

    // Conta de pagamento (origem do dinheiro nos lançamentos)
    for (const ct of [
      { name: 'Conta Corrente Itaú Personnalité — Agência 0912', type: 'checking' },
      { name: 'Poupança Caixa', type: 'savings' },
      { name: 'Carteira digital', type: 'digital_wallet' },
      { name: 'Conta digital Nubank', type: 'checking' },
      { name: 'Reserva de emergência — CDB com liquidez diária', type: 'savings' },
    ]) {
      const r = await api.post(u('/me/payment-accounts/'), { data: ct });
      expect(r.ok(), `conta "${ct.name}": ${r.status()} ${await r.text()}`).toBeTruthy();
    }

    // Despesa recorrente (tela de Recorrência)
    // OITO recorrências, cobrindo as quatro frequências e o "a cada N". A tabela
    // precisa descrever cada padrão numa coluna estreita ("Dia 5", "Toda
    // segunda", "A cada 3 meses"), e é com variedade que se vê se a descrição
    // cabe ou vira sopa de letras.
    for (const rec of [
      { title: 'Aluguel do apartamento com condomínio e IPTU incluídos', base_amount: 8_450.75, frequency: 'monthly', day_of_month: 5 },
      { title: 'Plano de saúde familiar', base_amount: 3_280.4, frequency: 'monthly', day_of_month: 12 },
      { title: 'Faxina', base_amount: 220, frequency: 'weekly', day_of_week: 2 },
      { title: 'Assinatura anual do software de edição de vídeo e banco de imagens', base_amount: 4_780, frequency: 'yearly', month_of_year: 3, day_of_month: 15 },
      { title: 'Mensalidade da academia com personal trainer duas vezes por semana', base_amount: 890.5, frequency: 'monthly', day_of_month: 8 },
      { title: 'Estacionamento mensal do prédio comercial', base_amount: 640, frequency: 'monthly', interval: 1, day_of_month: 1 },
      // `interval > 1` é a recorrência "a cada N", e ela EXIGE `start_date`: sem
      // âncora não há como saber a partir de quando contar os 3 meses. O
      // `interval: 1` acima é o preset legado e dispensa.
      { title: 'Manutenção preventiva do carro', base_amount: 1_350, frequency: 'monthly', interval: 3, day_of_month: 20, start_date: iso(60).slice(0, 10) },
      { title: 'Café', base_amount: 12.5, frequency: 'daily' },
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
    // TRÊS pessoas além da dona: nome longo, nome curto e nome com acento, para
    // ver o avatar de iniciais, a lista de membros e — principalmente — a
    // divisão de uma despesa entre quatro, que é onde os selos de participante
    // disputam espaço na linha.
    const convidados: Array<{ id: number; nome: string }> = [];
    for (const c of [
      { nome: 'Bruno Nascimento Albuquerque', email: 'bruno.demo@cf4.app', role: 'member', rendaBase: 42_300.5, cartao: 'Bradesco Elo Nanquim', limite: 45_000 },
      { nome: "Carla Íris D'Ávila", email: 'carla.demo@cf4.app', role: 'admin', rendaBase: 9_870.25, cartao: 'Santander Unique', limite: 28_000 },
      { nome: 'Téo', email: 'teo.demo@cf4.app', role: 'viewer', rendaBase: 3_150, cartao: 'Cartão pré-pago', limite: 2_000 },
    ]) {
      const apiC = await playwright.request.newContext();
      await apiC.post(u('/auth/register'), { data: { name: c.nome, email: c.email, password } });
      const log = await apiC.post(u('/auth/login'), { data: { email: c.email, password } });
      expect(log.ok(), `login de ${c.nome}: ${await log.text()}`).toBeTruthy();
      const eu2 = await (await apiC.get(u('/auth/me'))).json();

      const cv = await api.post(u(`/workspaces/${wsId}/invites`), {
        data: { email: c.email, role: c.role },
      });
      expect(cv.ok(), `convite de ${c.nome}: ${cv.status()} ${await cv.text()}`).toBeTruthy();
      const av = await (await apiC.get(u('/notifications'))).json();
      const tk = av.items.find((n: { invite_token?: string }) => n.invite_token)?.invite_token;
      expect(tk, `${c.nome} recebeu o convite`).toBeTruthy();
      expect((await apiC.post(u(`/invites/accept/${tk}`))).ok()).toBeTruthy();
      // Cada pessoa com o SEU patrimônio pessoal. Renda, cartão e conta são
      // recursos da pessoa (ADR 0021), então isso não aparece nas telas da Ana
      // — de propósito, é o que a privacidade garante. Aparece no painel
      // administrativo (contagem, uso, espaço) e torna o cenário verossímil em
      // vez de um único usuário rico cercado de contas zeradas.
      const rendaC = await apiC.post(u('/me/income/'), {
        data: { title: `Salário de ${c.nome.split(' ')[0]}`, amount: c.rendaBase, received_at: iso(7) },
      });
      expect(rendaC.ok(), `renda de ${c.nome}: ${rendaC.status()} ${await rendaC.text()}`).toBeTruthy();

      const cartaoC = await apiC.post(u('/me/credit-cards/'), {
        data: { name: c.cartao, limit: c.limite, closing_day: 10, due_day: 20 },
      });
      expect(cartaoC.ok(), `cartão de ${c.nome}: ${cartaoC.status()} ${await cartaoC.text()}`).toBeTruthy();

      convidados.push({ id: eu2.id, nome: c.nome });
      await apiC.dispose();
    }
    const bruno = convidados[0];

    // Despesas rateadas: é o que gera saldo devedor entre as duas pessoas.
    const todos = [uid, ...convidados.map((c) => c.id)];
    for (const d of [
      // Dois participantes
      { title: 'Jantar de comemoração no restaurante do hotel', total: 3_890.6, com: [uid, bruno.id] },
      { title: 'Viagem de fim de ano — hospedagem e passagens', total: 214_500, com: [uid, bruno.id] },
      // QUATRO participantes: é aqui que os selos de quem participou disputam a
      // largura da linha, na tela de Acertos e na lista de Lançamentos.
      { title: 'Churrasco de confraternização do fim de ano com as famílias', total: 2_480.9, com: todos },
      { title: 'Presente coletivo de casamento', total: 1_200, com: todos },
      { title: 'Aluguel da casa de praia no feriado prolongado de novembro', total: 18_900, com: todos },
      // Três participantes, valor alto
      { title: 'Reforma da área comum do prédio — rateio extraordinário', total: 96_750.44, com: todos.slice(0, 3) },
    ]) {
      const r = await api.post(u(`/workspaces/${wsId}/transactions/`), {
        data: {
          title: d.title,
          total_amount: d.total,
          transaction_date: iso(4),
          payers: [{ user_id: uid, amount: d.total }],
          splits: d.com.map((id) => ({ user_id: id, split_method: 'equal', input_value: 0 })),
        },
      });
      expect(r.ok(), `despesa rateada "${d.title}": ${r.status()} ${await r.text()}`).toBeTruthy();
    }

    // -----------------------------------------------------------------------
    // Os OUTROS tipos de divisão. Até aqui tudo era `equal`, e o catálogo não
    // mostrava porcentagem, valor fixo nem divisão por item — que são
    // justamente os modos onde a linha precisa exibir mais informação por
    // participante e onde o layout aperta.
    // -----------------------------------------------------------------------

    // Porcentagem desigual (60/25/15)
    const porcent = await api.post(u(`/workspaces/${wsId}/transactions/`), {
      data: {
        title: 'Conta de energia do escritório compartilhado — rateio por sala ocupada',
        total_amount: 4_820.35,
        transaction_date: iso(6),
        payment_method: 'pix',
        payers: [{ user_id: uid, amount: 4_820.35 }],
        splits: [
          { user_id: uid, split_method: 'percentage', input_value: 60 },
          { user_id: convidados[0].id, split_method: 'percentage', input_value: 25 },
          { user_id: convidados[1].id, split_method: 'percentage', input_value: 15 },
        ],
      },
    });
    expect(porcent.ok(), `divisão por porcentagem: ${porcent.status()} ${await porcent.text()}`).toBeTruthy();

    // Valor fixo por pessoa, e quem PAGOU não é a dona da tela
    const fixo = await api.post(u(`/workspaces/${wsId}/transactions/`), {
      data: {
        title: 'Assinatura do plano familiar de streaming dividida em valores combinados',
        total_amount: 189.9,
        transaction_date: iso(5),
        payment_method: 'boleto',
        payers: [{ user_id: convidados[0].id, amount: 189.9 }],
        splits: [
          { user_id: uid, split_method: 'fixed', input_value: 89.9 },
          { user_id: convidados[0].id, split_method: 'fixed', input_value: 60 },
          { user_id: convidados[1].id, split_method: 'fixed', input_value: 40 },
        ],
      },
    });
    expect(fixo.ok(), `divisão por valor fixo: ${fixo.status()} ${await fixo.text()}`).toBeTruthy();

    // Divisão POR ITEM: cada item com participantes próprios (ADR do rateio por
    // item). É o caso mais denso da interface — quantidade, valor unitário e
    // quem participa de cada linha.
    const porItem = await api.post(u(`/workspaces/${wsId}/transactions/`), {
      data: {
        title: 'Supermercado do mês — compras separadas por quem consome',
        total_amount: 1_284.59,
        transaction_date: iso(2),
        split_mode: 'item',
        payment_method: 'debit_card',
        payers: [{ user_id: uid, amount: 1_284.59 }],
        items: [
          { title: 'Carne, frango e peixe para a semana', amount: 486.9, quantity: 1, shares: [{ user_id: uid, split_method: 'equal', input_value: 0 }, { user_id: convidados[0].id, split_method: 'equal', input_value: 0 }] },
          { title: 'Ração e areia do gato', amount: 312.4, quantity: 2, unit_amount: 156.2, shares: [{ user_id: convidados[1].id, split_method: 'equal', input_value: 0 }] },
          { title: 'Fraldas', amount: 289.9, quantity: 1, shares: [{ user_id: convidados[0].id, split_method: 'equal', input_value: 0 }, { user_id: convidados[2].id, split_method: 'equal', input_value: 0 }] },
          { title: 'Café, filtro e açúcar', amount: 195.39, quantity: 3, unit_amount: 65.13, shares: [{ user_id: uid, split_method: 'equal', input_value: 0 }, { user_id: convidados[0].id, split_method: 'equal', input_value: 0 }, { user_id: convidados[1].id, split_method: 'equal', input_value: 0 }, { user_id: convidados[2].id, split_method: 'equal', input_value: 0 }] },
        ],
      },
    });
    expect(porItem.ok(), `divisão por item: ${porItem.status()} ${await porItem.text()}`).toBeTruthy();

    // Vários PAGADORES na mesma despesa (cada um adiantou uma parte)
    const multi = await api.post(u(`/workspaces/${wsId}/transactions/`), {
      data: {
        title: 'Material de construção da reforma — cada um adiantou uma parte',
        total_amount: 27_640.8,
        transaction_date: iso(8),
        payment_method: 'bank_transfer',
        payers: [
          { user_id: uid, amount: 15_000 },
          { user_id: convidados[0].id, amount: 8_640.8 },
          { user_id: convidados[1].id, amount: 4_000 },
        ],
        splits: todos.map((id) => ({ user_id: id, split_method: 'equal', input_value: 0 })),
      },
    });
    expect(multi.ok(), `múltiplos pagadores: ${multi.status()} ${await multi.text()}`).toBeTruthy();

    // Compra JÁ MOVIDA de fatura (ADR 0032). O deslocamento é a única coisa no
    // app que se vê apenas no detalhe de um lançamento, e sem uma linha assim o
    // catálogo mostraria o seletor sempre no estado neutro — que é o estado que
    // não precisa de explicação nenhuma.
    const deslocada = await api.post(u(`/workspaces/${wsId}/transactions/`), {
      data: {
        title: 'Jantar no restaurante — o cartão só processou dois dias depois',
        total_amount: 486.2,
        // Véspera do fechamento do primeiro cartão (dia 28), que é exatamente a
        // janela em que o atraso de captura decide a fatura.
        transaction_date: vesperaDoFechamento,
        payment_method: 'credit_card',
        credit_card_id: card!.id,
        statement_shift: 1,
        payers: [{ user_id: uid, amount: 486.2 }],
        splits: [{ user_id: uid, split_method: 'equal', input_value: 0 }],
      },
    });
    expect(
      deslocada.ok(),
      `compra deslocada de fatura: ${deslocada.status()} ${await deslocada.text()}`,
    ).toBeTruthy();
  }

  /**
   * Link de convite — a única rota do app que o catálogo nunca fotografou.
   *
   * Ela não aparece em menu nenhum (chega-se a ela por um link recebido), e é
   * por isso que passou despercebida: ninguém a encontra navegando. É também a
   * primeira tela que uma pessoa NOVA vê do produto, o que a torna das mais
   * importantes para conferir visualmente.
   *
   * Um token de verdade, não um inválido: com token quebrado a tela mostraria só
   * "convite não encontrado", e o que interessa ver é o convite legítimo — nome
   * do espaço, papel oferecido e o botão de aceitar.
   */
  const linkConvite = await api.post(u(`/workspaces/${wsId}/invites/link`), {
    data: { role: 'member', expires_days: 7, max_uses: 50 },
  });
  expect(
    linkConvite.ok(),
    `link de convite: ${linkConvite.status()} ${await linkConvite.text()}`,
  ).toBeTruthy();
  const tokenConvite: string = (await linkConvite.json()).token;

  // ----------------------------------------------------------- SCREENSHOTS
  await page.setViewportSize({ width: 1440, height: 900 });

  // Sempre injeta o workspace atual (persist do zustand) antes do app carregar.
  // NÃO mexe no theme aqui — o theme é controlado por evaluate+reload por fase.
  await page.addInitScript((ws) => {
    localStorage.setItem('cf4-ui', JSON.stringify({ state: { currentWorkspaceId: ws }, version: 0 }));
  }, wsId);

  /**
   * Captura o VIEWPORT, não a página inteira.
   *
   * Com `fullPage: true` a tela de Acertos saía 1440×5118 — uma tira de 3,5:1
   * que o GitHub renderiza como um risco ilegível na tabela do catálogo, e que
   * ninguém abre para ler. O catálogo existe para dar uma ideia da interface em
   * um relance; quem quer o resto roda o app.
   *
   * O viewport é 1440×900 e não 1920×1080 porque o conteúdo do `AppShell` é
   * limitado a `max-w-[1200px]`: a 1920 as capturas ganhariam ~250 px de vazio
   * de cada lado sem mostrar uma linha a mais. 1440 é a largura em que o layout
   * encosta no próprio limite.
   */
  const shot = async (slug: string) => {
    await page.screenshot({ path: path.join(SHOTS, `${slug}.png`) });
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

  /*
   * O convite de notificação (ADR 0033).
   *
   * Capturado ANTES de encerrar o onboarding não daria certo: ele se cala
   * enquanto `needs_onboarding` for true, de propósito — dois modais na primeira
   * tela é o caminho mais curto para a pessoa fechar os dois sem ler. Por isso
   * a captura vem logo DEPOIS do flip do flag, mais abaixo.
   */

  // Encerra o onboarding via API (flip do flag, sem criar renda/cartão) e recarrega
  await api.post(u('/auth/onboarding'), { data: { workspace_id: wsId, salary: 0 } });

  const capturarAvisoDeVencimento = async (theme: 'light' | 'dark') => {
    /*
     * `Notification.permission` precisa ser forçada para `'default'`, e o
     * motivo é uma limitação do navegador — não uma conveniência.
     *
     * No Chromium HEADLESS a permissão nasce `'denied'` e `grantPermissions()`
     * NÃO a altera (medido: 'denied' antes, depois e após reload). O resultado
     * é que a tela entra no estado "bloqueado": a faixa vira "Notificações
     * bloqueadas" e o convite nem abre, porque ele só aparece para quem ainda
     * PODE ativar. Foi exatamente assim que a primeira rodada saiu — duas telas
     * fotografando um estado que quase ninguém encontra.
     *
     * Num navegador de verdade a primeira visita é `'default'`. É esse estado
     * que o catálogo precisa mostrar, e no headless a única forma de alcançá-lo
     * é esta. Nada além da leitura da permissão é simulado: o componente, o
     * hook e a decisão de qual estado mostrar são os de produção.
     */
    await page.addInitScript(() => {
      Object.defineProperty(Notification, 'permission', {
        get: () => 'default',
        configurable: true,
      });
    });

    // O convite espera 1200ms antes de abrir (ver AtivarNotificacoes.tsx), e
    // some por uma semana assim que alguém clica "Agora não" — então a chave do
    // adiamento é limpa antes de cada captura.
    await page.goto('/overview');
    await page.evaluate((t) => {
      localStorage.setItem('theme', t);
      localStorage.removeItem('cf4:aviso-push-adiado-ate');
    }, theme);
    await page.reload();
    await page.getByRole('dialog').waitFor({ state: 'visible', timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(600);
    await shot(`aviso-convite-${theme}`);
    await page.keyboard.press('Escape').catch(() => {});

    // A faixa em Contas a pagar — onde a falta do aviso dói.
    await page.goto('/me/payables');
    await settle();
    await shot(`aviso-contas-a-pagar-${theme}`);
  };

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

    // Convite: fora da lista de rotas porque o caminho carrega um token gerado
    // na semeadura — `appRoutes` só conhece caminhos estáticos.
    await page.goto(`/invite/${tokenConvite}`);
    await settle();
    await shot(`convite-${theme}`);

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

    // Aviso da janela de fechamento + atalho para a fatura seguinte (ADR 0032).
    //
    // O aviso só existe com CARTÃO escolhido e data dentro dos três dias que
    // antecedem o fechamento — é uma combinação que nenhuma captura de rota
    // alcança, porque ela vive dentro do formulário e depende do que foi
    // preenchido. Sem estas linhas, a única coisa nova visível no catálogo
    // seria o seletor de fatura no detalhe.
    await page.goto(`/w/${wsId}`);
    await settle();
    const paraFechamento = page.getByRole('button', { name: 'Nova Despesa' });
    if (await paraFechamento.count()) {
      await paraFechamento.first().click();
      await page.getByRole('dialog').waitFor({ state: 'visible' }).catch(() => {});
      await page.getByLabel('Título / Descrição').fill('Jantar de aniversário');
      await page.getByLabel('Forma de pagamento').selectOption('credit_card');
      // Pelo NOME, não por índice. A lista de cartões não sai na ordem em que
      // foram semeados, e `{ index: 1 }` pegava o C6 Carbon (fecha dia 10):
      // com a data no dia 27, o destino ficava a duas semanas do fechamento e o
      // aviso — o objeto desta captura — simplesmente não aparecia. A captura
      // saía "verde" mostrando o formulário sem a novidade.
      const seletorDeCartao = page.getByLabel('Qual cartão?');
      const platinum = await seletorDeCartao
        .locator('option', { hasText: 'Platinum' })
        .first()
        .getAttribute('value');
      expect(platinum, 'o cartão de fechamento 28 precisa estar na lista').toBeTruthy();
      await seletorDeCartao.selectOption(platinum!);
      await page.getByLabel('Data', { exact: true }).fill(vesperaDoFechamento.slice(0, 10));
      // O aviso depende de uma ida ao servidor (`statement-for`): esperar o
      // testid em vez de um timeout fixo evita capturar o instante anterior a
      // ele, que é justamente a tela sem a novidade.
      await page
        .getByTestId('closing-window-warning')
        .waitFor({ state: 'visible', timeout: 10_000 })
        .catch(() => {});
      await shot(`aviso-janela-de-fechamento-${theme}`);
      await page.keyboard.press('Escape').catch(() => {});
      await page.waitForTimeout(300);
    }

    // Seletor "em qual fatura esta compra entrou" no detalhe do lançamento.
    // É a correção DEPOIS de lançada — a metade que resolve o problema, porque
    // é quando a fatura real já chegou e a dúvida virou fato.
    await page.goto(`/w/${wsId}/transactions`);
    await settle();
    const compraNoCartao = page.getByText(/o cartão só processou dois dias depois/i).first();
    if (await compraNoCartao.count()) {
      await compraNoCartao.click();
      await page.getByRole('dialog').waitFor({ state: 'visible' }).catch(() => {});
      await page
        .getByLabel('Fatura desta compra')
        .waitFor({ state: 'visible', timeout: 10_000 })
        .catch(() => {});
      // O `waitFor` acima garante que o seletor EXISTE, não que o fade-in do
      // diálogo terminou: sem esta pausa a captura saía com o modal a meio
      // caminho, translúcido e por cima da lista.
      await page.waitForTimeout(600);
      await shot(`detalhe-lancamento-fatura-${theme}`);
      await page.keyboard.press('Escape').catch(() => {});
      await page.waitForTimeout(300);
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

  await capturarAvisoDeVencimento('light');
  await capturarAvisoDeVencimento('dark');

  // ---- Mobile (bottom-nav + responsivo), nos DOIS temas ----
  //
  // 390×844 é o viewport CSS do iPhone 12/13/14 e do 15/16 base — a resolução
  // mais comum em uso hoje, e a referência que a maioria dos aparelhos Android
  // de tela grande também aproxima. Não é DPR real (o aparelho é 3x); o que
  // importa aqui é a largura em CSS px, que é o que decide qual breakpoint do
  // Tailwind entra.
  await page.setViewportSize({ width: 390, height: 844 });

  /*
   * TODAS as rotas, e não uma amostra de cinco.
   *
   * A amostra anterior cobria Início, Lançamentos, Relatórios, Cartões e Meus
   * acertos — e as telas que mais estouravam no celular (Rendas, com três ações
   * no cabeçalho; Administração, com seis abas; Importar, em duas colunas;
   * Financiamentos, com uma tabela de sete colunas) não estavam entre elas.
   * Um catálogo que fotografa só o que já se sabe estar bom não descobre nada.
   */
  const capturarMobile = async (theme: 'light' | 'dark') => {
    await page.goto('/overview');
    await page.evaluate((t) => localStorage.setItem('theme', t), theme);
    await page.reload();
    await settle();
    for (const r of appRoutes(wsId)) {
      await page.goto(r.path);
      await settle();
      await shot(`mobile-${r.slug}-${theme}`);
    }
    await page.goto(`/invite/${tokenConvite}`);
    await settle();
    await shot(`mobile-convite-${theme}`);

    // A gaveta "Mais" e o seletor de escopo só existem no celular: são a
    // navegação inteira abaixo de `md`, e nunca tinham sido fotografados.
    await page.goto(`/w/${wsId}/transactions`);
    await settle();
    const mais = page.locator('nav').last().getByText('Mais', { exact: true });
    if (await mais.count()) {
      await mais.click();
      await page.getByRole('dialog').waitFor({ state: 'visible' }).catch(() => {});
      await page.waitForTimeout(500);
      await shot(`mobile-gaveta-mais-${theme}`);
      await page.keyboard.press('Escape').catch(() => {});
      await page.waitForTimeout(300);
    }
    const escopo = page.getByRole('button', { name: /Casa|Espaço|Pessoal|Meu/ }).first();
    if (await escopo.count()) {
      await escopo.click();
      await page.getByRole('dialog').waitFor({ state: 'visible' }).catch(() => {});
      await page.waitForTimeout(500);
      await shot(`mobile-seletor-de-escopo-${theme}`);
      await page.keyboard.press('Escape').catch(() => {});
      await page.waitForTimeout(300);
    }

    // O formulário de despesa é o mais denso do app e vira bottom sheet aqui.
    const novaBtn = page.getByRole('button', { name: 'Nova despesa' }).first();
    if (await novaBtn.count()) {
      await novaBtn.click();
      await page.getByRole('dialog').waitFor({ state: 'visible' }).catch(() => {});
      await page.waitForTimeout(600);
      await shot(`mobile-nova-despesa-${theme}`);
      await page.keyboard.press('Escape').catch(() => {});
    }
  };
  await capturarMobile('light');
  await capturarMobile('dark');

  console.log(`\n>>> Screenshots salvos em: ${SHOTS}\n`);
});
