import AxeBuilder from '@axe-core/playwright';
import { test, expect, type Page } from '@playwright/test';

/*
 * F5.3 do roadmap de redesign — a auditoria de acessibilidade que nunca tinha
 * rodado. Cobre as telas que mais importam: a PRIMEIRA que um usuário novo vê
 * (onboarding), a que ele usa todo dia (Início), o formulário mais rico do app
 * (Nova Despesa) e a mais densa em cor/gráfico (Relatórios).
 *
 * Escopo: `wcag2a` + `wcag2aa` — as violações que são realmente defeito, não
 * preferência de estilo. Falha o teste, não avisa: um regressor de contraste ou
 * de rótulo passa despercebido em revisão de código.
 */
const API = 'http://localhost:8000/api/v1';
const PADRAO = ['wcag2a', 'wcag2aa'];

/**
 * Erro de console é FALHA, não ruído.
 *
 * A auditoria externa encontrou `DialogContent requires a DialogTitle` repetido
 * no log do runner — um defeito de acessibilidade real (diálogo sem nome
 * acessível) que nenhum teste via, porque o axe mede o DOM e o React reporta
 * isso via `console.error`. Aqui os dois sinais passam a valer.
 *
 * A lista de exceções é curta e explícita de propósito: o que não estiver nela
 * quebra o teste.
 */
const RUIDO_ACEITAVEL = [
  'WebSocket connection',            // Vite HMR reconectando em dev
  'Download the React DevTools',
];

function vigiarConsole(page: Page): string[] {
  const erros: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() !== 'error' && msg.type() !== 'warning') return;
    const texto = msg.text();
    if (RUIDO_ACEITAVEL.some((ok) => texto.includes(ok))) return;
    erros.push(`[${msg.type()}] ${texto}`);
  });
  page.on('pageerror', (err) => erros.push(`[pageerror] ${err.message}`));
  return erros;
}

/**
 * Espera as animações de entrada TERMINAREM antes de medir.
 *
 * Sem isto o axe fotografa a tela no meio do `fade-in` — com o elemento ainda
 * semitransparente — e reporta falha de contraste em texto que, parado, passa
 * folgado. O sintoma só apareceu quando as animações voltaram a funcionar: o
 * `tw-animate-css` era escrito em sintaxe Tailwind v4 num projeto v3 e não
 * gerava CSS nenhum, então nada animava e a corrida não existia.
 */
async function aguardarAnimacoes(page: Page) {
  await page.waitForFunction(
    () =>
      document.getAnimations().every((a) => {
        if (a.playState !== 'running') return true;
        // Animação INFINITA (spinner, `animate-pulse` de skeleton) nunca termina
        // — esperar por ela é esperar para sempre. O que interessa aqui é a
        // animação de ENTRADA, que tem fim: é ela que faz o axe fotografar o
        // texto semitransparente e reportar contraste falso.
        const iteracoes = (a.effect?.getTiming().iterations ?? 1) as number;
        return iteracoes === Infinity;
      }),
    undefined,
    { timeout: 5_000 },
  );
}

async function analisar(page: Page, seletor?: string) {
  await aguardarAnimacoes(page);
  let builder = new AxeBuilder({ page }).withTags(PADRAO);
  if (seletor) builder = builder.include(seletor);
  return builder.analyze();
}

/** Erro legível: o dump cru do axe não diz em qual elemento o problema está. */
function resumir(violations: Awaited<ReturnType<typeof analisar>>['violations']) {
  return violations
    .map((v) => `${v.id} (${v.impact}): ${v.help}\n    ${v.nodes.map((n) => n.target.join(' ')).join('\n    ')}`)
    .join('\n\n');
}

async function contaNova(browser: Parameters<Parameters<typeof test>[1]>[0]['browser']) {
  const ts = Date.now() + Math.floor(Math.random() * 1000);
  const email = `a11y${ts}@e2e.com`;
  const context = await browser.newContext();
  await context.request.post(`${API}/auth/register`, {
    data: { name: 'Ana Acessível', email, password: 'senha123' },
  });
  await context.request.post(`${API}/auth/login`, {
    data: { email, password: 'senha123' },
  });
  return context;
}

test.describe('Acessibilidade (axe · WCAG 2 A/AA)', () => {
  test('Onboarding — a primeira tela do usuário novo', async ({ browser }) => {
    const context = await contaNova(browser);
    const page = await context.newPage();
    const erros = vigiarConsole(page);
    await page.goto('/');

    // Sem concluir o onboarding, o modal bloqueante é o que está na tela
    const dialogo = page.getByRole('dialog');
    await expect(dialogo).toBeVisible();

    const { violations } = await analisar(page);
    expect(resumir(violations)).toBe('');
    expect(erros).toEqual([]);
    await context.close();
  });

  test('Início global, painel do workspace e Nova Despesa', async ({ browser }) => {
    const context = await contaNova(browser);
    const [ws] = await (await context.request.get(`${API}/workspaces/`)).json();
    await context.request.post(`${API}/auth/onboarding`, { data: { salary: 4000 } });
    expect(ws.id).toBeTruthy();

    const page = await context.newPage();
    const erros = vigiarConsole(page);

    // Início GLOBAL (ADR 0020): soma todos os workspaces, e é só leitura —
    // lançar despesa é ato de UMA casa, então o botão não mora aqui.
    await page.goto('/overview');
    await expect(page.getByRole('heading', { name: /Seu mês/ })).toBeVisible();
    const global = await analisar(page);
    expect(resumir(global.violations)).toBe('');

    // Painel do workspace: é onde se lança
    await page.goto(`/w/${ws.id}`);
    await expect(page.getByRole('heading', { name: /Painel/ })).toBeVisible();
    const inicio = await analisar(page);
    expect(resumir(inicio.violations)).toBe('');

    await page.locator('header').getByRole('button', { name: 'Nova despesa' }).click();
    await expect(page.getByRole('dialog')).toBeVisible();
    // Inclui as "Opções avançadas": é onde moram os campos de divisão
    await page.getByRole('dialog').getByRole('button', { name: /Opções avançadas/ }).click();

    const form = await analisar(page, '[role="dialog"]');
    expect(resumir(form.violations)).toBe('');
    // Pega o `DialogContent requires a DialogTitle` que só aparecia no log
    expect(erros).toEqual([]);
    await context.close();
  });

  test('Relatórios — a tela mais densa em cor', async ({ browser }) => {
    const context = await contaNova(browser);
    await context.request.post(`${API}/auth/onboarding`, { data: { salary: 4000 } });

    const page = await context.newPage();
    const erros = vigiarConsole(page);
    await page.goto('/reports');
    await expect(page.getByRole('heading', { name: /Relatórios/i })).toBeVisible();

    const { violations } = await analisar(page);
    expect(resumir(violations)).toBe('');
    expect(erros).toEqual([]);
    await context.close();
  });

  /*
   * As DUAS telas de configuração, depois da separação pessoal × workspace.
   *
   * Nenhuma delas tinha cobertura: o audit de console visitava `/settings` com a
   * aba PERFIL aberta, que era o padrão — a aba de Membros, com o formulário de
   * convite, o seletor de moeda-base e a tabela de papéis, nunca chegou a ser
   * renderizada por teste nenhum. Agora ela é o padrão do workspace, e
   * `/me/settings` é uma tela nova inteira.
   */
  test('Configurações do workspace — a aba de Membros', async ({ browser }) => {
    const context = await contaNova(browser);
    const [ws] = await (await context.request.get(`${API}/workspaces/`)).json();
    await context.request.post(`${API}/auth/onboarding`, { data: { salary: 4000 } });

    const page = await context.newPage();
    const erros = vigiarConsole(page);
    await page.goto(`/w/${ws.id}/settings`);
    await expect(
      page.getByRole('heading', { name: /Configurações do espaço/i }),
    ).toBeVisible();
    // O que a aba padrão desenha: nome, moeda-base, convite e papéis.
    await expect(page.getByText('Moeda-base')).toBeVisible();

    const { violations } = await analisar(page);
    expect(resumir(violations)).toBe('');
    expect(erros).toEqual([]);
    await context.close();
  });

  test('Extrato global — a página que o scanner nunca tinha visitado', async ({ browser }) => {
    const context = await contaNova(browser);
    await context.request.post(`${API}/auth/onboarding`, { data: { salary: 4000 } });

    const page = await context.newPage();
    const erros = vigiarConsole(page);
    await page.goto('/me/ledger');
    await expect(page.getByRole('heading', { name: /Extrato/i })).toBeVisible();

    const { violations } = await analisar(page);
    expect(resumir(violations)).toBe('');
    expect(erros).toEqual([]);
    await context.close();
  });

  test('Seus acertos — tabela densa, badges de status e navegador de mês', async ({ browser }) => {
    // A superfície nova do ADR 0027, e a mais densa depois de Relatórios: uma
    // tabela por casa, badges de status, botões só com ícone no navegador de
    // mês. Toda tela nova deste projeto que não entrou aqui no mesmo commit
    // acabou entrando meses depois com o título "a página que o scanner nunca
    // tinha visitado" — três vezes até agora.
    const context = await contaNova(browser);
    await context.request.post(`${API}/auth/onboarding`, { data: { salary: 4000 } });

    const page = await context.newPage();
    const erros = vigiarConsole(page);
    await page.goto('/me/settlements');
    await expect(page.getByRole('heading', { name: 'Seus acertos' })).toBeVisible();

    const { violations } = await analisar(page);
    expect(resumir(violations)).toBe('');
    expect(erros).toEqual([]);
    await context.close();
  });

  test('o par de aviso do tema passa o contraste nos DOIS temas', async ({ browser }) => {
    // O axe só vê o que está na tela, e o aviso de "valores sem cotação" só
    // aparece quando há valores sem cotação — um estado que nenhum spec produz.
    // A violação real (2,42:1) vivia no TOKEN `--warning`, usado como cor de
    // texto em uma dúzia de componentes; medi-lo direto cobre todos de uma vez.
    //
    // Os pixels e não `getComputedStyle`: o Chromium devolve a string `oklch()`
    // crua, que não dá para comparar. O canvas entrega o que o olho recebe.
    const context = await contaNova(browser);
    const page = await context.newPage();
    await page.goto('/');

    for (const tema of ['light', 'dark'] as const) {
      const razao = await page.evaluate((t) => {
        document.documentElement.classList.toggle('dark', t === 'dark');
        const sonda = document.createElement('div');
        sonda.className = 'bg-warning-subtle text-warning';
        document.body.appendChild(sonda);
        const cs = getComputedStyle(sonda);
        const fgCss = cs.color;
        const bgCss = cs.backgroundColor;
        sonda.remove();

        const cv = document.createElement('canvas');
        cv.width = 2;
        cv.height = 2;
        const ctx = cv.getContext('2d')!;
        const px = (cor: string) => {
          ctx.clearRect(0, 0, 2, 2);
          ctx.fillStyle = cor;
          ctx.fillRect(0, 0, 2, 2);
          const d = ctx.getImageData(0, 0, 1, 1).data;
          return [d[0], d[1], d[2]] as const;
        };
        const lin = (c: number) => {
          const v = c / 255;
          return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
        };
        const L = (v: readonly [number, number, number]) =>
          0.2126 * lin(v[0]) + 0.7152 * lin(v[1]) + 0.0722 * lin(v[2]);
        const a = L(px(fgCss));
        const b = L(px(bgCss));
        return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
      }, tema);

      expect(razao, `contraste do aviso no tema ${tema}`).toBeGreaterThanOrEqual(4.5);
    }
    await context.close();
  });

  test('Configurações pessoais — alcançáveis sem workspace na URL', async ({ browser }) => {
    const context = await contaNova(browser);
    await context.request.post(`${API}/auth/onboarding`, { data: { salary: 4000 } });

    const page = await context.newPage();
    const erros = vigiarConsole(page);
    // Sem `/w/:id` no caminho: perfil, senha, contas e aparência ficavam presos
    // dentro do workspace, e quem não tivesse um válido não os alcançava.
    await page.goto('/me/settings');
    await expect(page.getByRole('heading', { name: /Suas configurações/i })).toBeVisible();
    // A moeda de relatório: o `useSetReportCurrency` existia sem tela nenhuma.
    await expect(page.getByText('Moeda de relatório')).toBeVisible();

    const { violations } = await analisar(page);
    expect(resumir(violations)).toBe('');
    expect(erros).toEqual([]);
    await context.close();
  });

  /*
   * ADMINISTRAÇÃO DO SITE — a tela mais nova (ADR 0026) e a mais densa em
   * controle: abas, tabelas de pessoas, formulário de configuração, lista de
   * convites e a trilha de auditoria. O scanner nunca tinha entrado aqui, que é
   * exatamente onde um regressor de rótulo ou de contraste passa despercebido.
   *
   * A conta nasce pela JANELA DE BOOTSTRAP: `SUPERADMIN_EMAIL` está no `env` do
   * backend do e2e (ver `scripts/e2e.mjs`), e a primeira conta com aquele
   * endereço nasce superadministradora. Sem isso não há caminho de teste para
   * `/admin` — e era por isso que a tela ficava de fora.
   */
  test('Administração do site — a tela que o scanner nunca tinha visitado', async ({ browser }) => {
    const context = await browser.newContext();
    const email = 'admin-a11y@e2e.com';
    await context.request.post(`${API}/auth/register`, {
      data: { name: 'Admin A11y', email, password: 'senha123' },
    });
    const login = await context.request.post(`${API}/auth/login`, {
      data: { email, password: 'senha123' },
    });
    expect(login.ok(), 'a janela de bootstrap não criou o superadministrador').toBeTruthy();
    const me = await (await context.request.get(`${API}/auth/me`)).json();
    expect(me.platform_role, `papel recebido: ${JSON.stringify(me)}`).toBe('superadmin');
    // Onboarding CONCLUÍDO antes de navegar, como nos demais testes daqui. Sem
    // isto o modal de boas-vindas abre por cima de qualquer rota, e o Radix
    // marca todo o resto da página com `aria-hidden` — o `h1` da tela existe no
    // DOM e some da árvore de acessibilidade, que é exatamente o que o axe (e o
    // `getByRole`) enxergam. O sintoma era "element(s) not found" numa página
    // que o snapshot mostrava inteira.
    await context.request.post(`${API}/auth/onboarding`, { data: { salary: 4000 } });

    const page = await context.newPage();
    const erros = vigiarConsole(page);
    await page.goto('/admin');
    // Timeout folgado SÓ aqui: `/admin` é `React.lazy` e esta é a única visita
    // da suíte, então o servidor de desenvolvimento compila o chunk na hora.
    await expect(page.getByRole('heading', { name: /Administração/i })).toBeVisible({
      timeout: 30_000,
    });

    // Cada aba é uma tela diferente: varrer só a primeira mediria um quinto.
    const { violations } = await analisar(page);
    expect(resumir(violations)).toBe('');

    for (const aba of [/Pessoas/i, /Convites/i, /Configurações/i, /Auditoria/i]) {
      const alvo = page.getByRole('tab', { name: aba });
      if (await alvo.count() === 0) continue;
      await alvo.click();
      const resultado = await analisar(page);
      expect(resumir(resultado.violations), `aba ${aba}`).toBe('');
    }
    expect(erros).toEqual([]);
    await context.close();
  });

  /*
   * As telas PÚBLICAS, que a suíte nunca tinha visitado.
   *
   * Todo teste acima entra com uma conta criada por `contaNova` — ou seja, a
   * varredura de console só via o app com sessão. Em `/login` e `/register` o
   * app sondava `/auth/me` (401) e o interceptor emendava `/auth/refresh` (401),
   * então a primeira tela que um usuário novo vê abria com dois erros de rede.
   *
   * `browser.newContext()` cru, sem cadastro: é o navegador limpo de quem chega
   * pela primeira vez, que é o cenário exato do defeito.
   */
  for (const [rota, botao] of [
    ['/login', /Acessar Conta/i],
    // `^Cadastrar$`: sem a âncora, casa também o "Cadastrar com Google" ao lado.
    ['/register', /^Cadastrar$/],
  ] as const) {
    test(`${rota} — tela pública sem erro de console`, async ({ browser }) => {
      const context = await browser.newContext();
      const page = await context.newPage();
      const erros = vigiarConsole(page);

      await page.goto(rota);
      // Âncora no botão de envio, não num heading: os títulos destas telas são
      // `CardTitle`, que o shadcn renderiza como `div`.
      await expect(page.getByRole('button', { name: botao })).toBeVisible();

      const { violations } = await analisar(page);
      expect(resumir(violations)).toBe('');
      // Uma 401 de rede também chega aqui como mensagem de console, e é por isso
      // que este `expect` é o que trava a regressão da sonda em rota pública.
      expect(erros).toEqual([]);
      await context.close();
    });
  }
});
