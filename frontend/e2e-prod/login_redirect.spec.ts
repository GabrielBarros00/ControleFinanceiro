import { test, expect, Page } from '@playwright/test';
import { postWithRetry } from './helpers';

// Regressão do bug: registro/login atrás do nginx (porta != 80) não redirecionava
// ao dashboard e qualquer rota protegida devolvia ao /login mesmo com cookie válido
// (307 de barra final com Location sem porta → clearStore no use-auth).

// Rotas PESSOAIS (`/me/...`) e do WORKSPACE, misturadas de propósito: o que se
// mede aqui é que nenhuma delas devolve ao /login com a sessão válida.
// `/income`, `/cards`, `/financing` e `/liabilities` são rotas ANTIGAS que
// redirecionam para os equivalentes pessoais (ADR 0021) — deixá-las na lista
// também cobre esse redirecionamento.
const PAGES: Array<[string, string]> = [
  // Pessoais (ADR 0021)
  ['/overview', 'Seu mês'],
  ['/me/income', 'Rendas'],
  ['/me/cards', 'Cartões'],
  ['/me/financing', 'Financiamentos'],
  ['/me/commitments', 'Compromissos financeiros'],
  ['/me/settlements', 'Seus acertos'],
  // Rotas ANTIGAS: redirecionam para os equivalentes pessoais — mantê-las aqui
  // cobre o redirecionamento além do bounce.
  ['/income', 'Rendas'],
  ['/cards', 'Cartões'],
  ['/liabilities', 'Compromissos financeiros'],
  // Do workspace
  ['/transactions', 'Lançamentos'],
  ['/reports', 'Relatórios'],
  ['/recurring', 'Recorrência'],
  // Só "Acertos": desde o ADR 0027 o título traz o NOME da casa
  // (`Acertos · Meu Workspace`), para não ser lido como o total da pessoa. O
  // `name` do `getByRole` casa por substring, então o prefixo basta — e ele
  // sobrevive a quem renomear o workspace.
  ['/debts', 'Acertos'],
  ['/import', 'Importar'],
  ['/settings', 'Configurações'],
];

async function expectNotBouncedToLogin(page: Page, path: string) {
  await page.goto(path);
  // O bounce acontece após a query de /auth/me; espera a rede assentar
  await page.waitForLoadState('networkidle');
  await expect(page, `rota ${path} devolveu ao /login`).not.toHaveURL(/\/login/);
}

test.describe('Sessão atrás do nginx (stack de produção)', () => {
  const ts = Date.now();
  const email = `e2e_prod_${ts}@teste.com`;
  const password = 'senha123';

  test('registro → dashboard → F5 e navegação mantêm a sessão → logout', async ({ page }) => {
    // 1. Registro com auto-login deve cair no dashboard, não voltar ao /login
    await page.goto('/register');
    await page.getByLabel('Nome Completo').fill('Usuária E2E Prod');
    await page.getByLabel('E-mail').fill(email);
    await page.getByLabel('Senha', { exact: true }).fill(password);
    await page.getByLabel('Confirmar', { exact: true }).fill(password);
    // O rate limit de auth (por IP+rota) vale aqui como em produção — é
    // deliberado não desligá-lo. O resto da suíte o absorve com `postWithRetry`,
    // mas este teste registra pelo FORMULÁRIO de propósito (o que ele verifica é
    // o redirecionamento do navegador atrás do nginx), e um formulário não tem
    // como ser "retentado" por um helper de request. Sem isto, a suíte inteira
    // gasta a janela em ~9 registros e este teste falha por vez sim, vez não —
    // um gate de deploy que reprova sozinho ensina a ignorar o vermelho.
    for (let tentativa = 0; tentativa < 8; tentativa++) {
      await page.getByRole('button', { name: 'Cadastrar', exact: true }).click();
      try {
        await expect(page).toHaveURL(/\/overview$/, { timeout: 8_000 });
        break;
      } catch {
        // Continua em /register: janela estourada. Espera e reenvia o mesmo
        // formulário — os campos seguem preenchidos.
        await page.waitForTimeout(10_000);
      }
    }

    await expect(page).toHaveURL(/\/overview$/, { timeout: 15_000 });
    // O que está na tela do usuário novo é o ONBOARDING, não o painel: ele é um
    // diálogo modal e torna o resto da página inerte, então procurar o heading
    // "Seu mês" aqui é procurar algo que o leitor de tela também não alcança.
    // A asserção passava por corrida — o modal abre num efeito, depois que
    // `/auth/me` responde, e antes o login resolvia sem esperar essa resposta.
    await expect(page.getByRole('dialog')).toBeVisible({ timeout: 15_000 });

    // 2. Onboarding mínimo (salário + pular cartão; "Pular" recarrega a página)
    await page.getByRole('button', { name: /Começar Setup/ }).click();
    await page.getByLabel('Salário / Renda Líquida').fill('5000,00');
    await page.getByRole('button', { name: 'Próximo Passo' }).click();
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'load' }),
      page.getByRole('button', { name: 'Pular esta etapa' }).click(),
    ]);
    await expect(page.getByRole('heading', { name: 'Seu mês' })).toBeVisible({ timeout: 15_000 });

    // 3. F5 mantém a sessão (era o sintoma: reload devolvia ao /login)
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Seu mês' })).toBeVisible({ timeout: 15_000 });
    await expect(page).not.toHaveURL(/\/login/);

    // 4. Todas as rotas protegidas abrem sem bounce
    for (const [path, title] of PAGES) {
      await expectNotBouncedToLogin(page, path);
      // Escopado ao header do Layout: páginas podem repetir o título em h2
      await expect(page.locator('header').getByRole('heading', { name: title })).toBeVisible({ timeout: 15_000 });
    }

    // 5. Logout devolve ao /login e rota protegida volta a exigir sessão
    await page.goto('/settings');
    await page.getByRole('button', { name: /Sair da Conta/ }).click();
    await expect(page).toHaveURL(/\/login/, { timeout: 15_000 });
    await page.goto('/');
    await expect(page).toHaveURL(/\/login/, { timeout: 15_000 });
  });

  test('login manual redireciona ao dashboard', async ({ page }) => {
    // Autossuficiente: worker pode reiniciar entre testes (ts é reavaliado),
    // então cria a própria conta via API antes do login pela UI
    // Pelo helper com retry em 429, como o resto da suíte: o rate limit de auth
    // vale por IP+rota e a suíte inteira roda em menos de dois minutos. Esta
    // era a ÚNICA chamada de registro que batia direto, então ela era a que caía
    // quando um spec novo entrava na janela — falha de infraestrutura do teste
    // que parecia defeito do login.
    const email2 = `e2e_prod_login_${Date.now()}@teste.com`;
    const res = await postWithRetry(page.request, '/api/v1/auth/register', {
      name: 'Login E2E Prod', email: email2, password,
    });
    if (!res.ok()) throw new Error(`registro via API falhou: ${res.status()}`);

    await page.goto('/login');
    await page.getByLabel('E-mail').fill(email2);
    await page.getByLabel('Senha', { exact: true }).fill(password);
    // Mesmo laço do registro pelo formulário, no primeiro teste, e pelo mesmo
    // motivo — aqui ele faltava. O `smoke_prod.py` TERMINA martelando
    // `/auth/login` até receber 429 (é o check "rate limit ativo"), e no CI a
    // suíte e2e-prod roda logo depois, no mesmo job: este login chegava com a
    // janela do IP já gasta. O teste passava ou falhava conforme a velocidade da
    // execução — um gate de deploy que reprova sozinho ensina a ignorar o
    // vermelho. `postWithRetry` não serve: um formulário não é uma requisição
    // que um helper possa reenviar.
    for (let tentativa = 0; tentativa < 8; tentativa++) {
      await page.getByRole('button', { name: /Acessar Conta/ }).click();
      try {
        await expect(page).toHaveURL(/\/overview$/, { timeout: 8_000 });
        break;
      } catch {
        // Continua em /login: janela estourada. Espera e reenvia o mesmo
        // formulário — os campos seguem preenchidos.
        await page.waitForTimeout(10_000);
      }
    }

    await expect(page).toHaveURL(/\/overview$/, { timeout: 15_000 });
    // Conta recém-criada: quem está na tela é o onboarding (modal), que torna o
    // resto da página inerte. O que este teste mede é o redirecionamento do
    // login atrás do nginx — e ele aconteceu.
    await expect(page.getByRole('dialog')).toBeVisible({ timeout: 15_000 });
  });
});
