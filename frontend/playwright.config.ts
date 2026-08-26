import { defineConfig, devices } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

// Python do VENV do projeto, não o do PATH. `python -m uvicorn` pegava qualquer
// interpretador que estivesse na frente no PATH — numa máquina com Python 3.13
// global isso subia um interpretador sem as dependências, e a suíte inteira
// morria no import (`MissingBackendError: argon2`) antes do primeiro teste, com o
// erro escondido no log do webServer.
//
// Caminho ABSOLUTO e entre aspas: o `command` vai para o shell do sistema, e no
// cmd.exe um relativo com barras normais (`../.venv/...`) vira
// "'..' não é reconhecido como um comando". Mesma resolução de plataforma que o
// Makefile faz para `VENV_BIN`; `E2E_PYTHON` permite apontar para outro.
// `import.meta.dirname` (não `__dirname`): o package é `"type": "module"`.
const VENV_PYTHON = path.resolve(
  import.meta.dirname,
  '..',
  '.venv',
  process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
);
const PYTHON = JSON.stringify(process.env.E2E_PYTHON ?? VENV_PYTHON);

// Quem sobe os servidores: `scripts/e2e.mjs` (o caminho de `npm run test:e2e`)
// marca esta variável e assume o ciclo de vida inteiro — inclusive o de MATÁ-LOS,
// que é a parte que o Playwright não fazia direito no Windows e deixava o comando
// pendurado depois de a suíte passar.
const SERVIDORES_EXTERNOS = !!process.env.E2E_EXTERNAL_SERVERS;

/*
 * Apaga o banco descartável antes da rodada.
 *
 * Só vale para quem chama `playwright test` na mão. O caminho oficial é
 * `npm run test:e2e` (`scripts/e2e.mjs`), que apaga o banco e sobe os servidores
 * ele mesmo — ver `E2E_EXTERNAL_SERVERS` no `webServer`, mais abaixo.
 *
 * Aqui e não num `globalSetup`: o Playwright sobe o `webServer` ANTES de rodar o
 * globalSetup, então lá o backend já abriu o arquivo e o `rm` falha com EPERM no
 * Windows. O corpo do módulo de config é avaliado antes de qualquer processo ser
 * criado, que é exatamente a janela necessária.
 */
const E2E_DB = path.resolve(import.meta.dirname, '..', 'backend', 'e2e.db');
// Só no processo PRINCIPAL, e só quando somos nós que subimos o backend: o
// Playwright reimporta a config em cada worker, e lá o banco já está aberto —
// apagar de novo falharia com EPERM no Windows (e, pior, apagaria o banco no
// meio da rodada em outros SOs). `TEST_WORKER_INDEX` só existe nos workers.
if (process.env.TEST_WORKER_INDEX === undefined && !SERVIDORES_EXTERNOS) {
  // `-wal`/`-shm` junto: sem eles o SQLite reconstrói o estado recém-apagado.
  for (const arquivo of [E2E_DB, `${E2E_DB}-wal`, `${E2E_DB}-shm`]) {
    fs.rmSync(arquivo, { force: true });
  }
}

export default defineConfig({
  testDir: './e2e',
  /*
   * `fullyParallel: false` + `workers: 2`: paralelo por ARQUIVO, nunca por teste.
   *
   * Os dois números saíram de medição, e o teto NÃO é o banco — é o custo de
   * criar usuário. Cada um dos 42 testes fabrica a própria conta, e
   * `register` + `login` são dois hashes argon2id de 64 MiB com
   * `parallelism=2` (`app/core/security.py`, caro de propósito). Com 4 workers
   * isso são quatro hashes simultâneos em cima dos 4 vCPUs que o runner do
   * GitHub tem: o uvicorn para de responder, `POST /auth/register` pendura até
   * o timeout de 30 s e a rodada cai em bloco.
   *
   * Está contado: 100 rodadas da suíte com `workers: 4` deram 14 reprovações —
   * 13 delas com o backend pendurado (as rodadas ruins levam 330 s no lugar de
   * 121 s, que é a assinatura da saturação). Não é intermitência de teste; é
   * fila no servidor. Aumentar o número aqui exigiria baratear o argon2 do
   * backend de e2e, e essa é uma decisão de segurança, não de CI.
   *
   * `fullyParallel: true` (paralelo por TESTE) está fora por outro motivo: as
   * telas de `/admin` são visões GLOBAIS do site. O `a11y.spec.ts` escaneia a
   * aba Pessoas enquanto os testes vizinhos criam usuários, e o axe passa a
   * medir uma tabela que ninguém escreveu. Reprovou em 1 de 2 rodadas assim, e
   * aparece em ~1% das rodadas mesmo com paralelismo por arquivo.
   *
   * Ganho medido em 4 núcleos, que é o que o runner tem: 198 s -> 148 s.
   */
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 2,
  /*
   * `open: 'never'` é o que faz o comando devolver o terminal.
   *
   * O atalho `reporter: 'html'` mantém o default `open: 'on-failure'`, e nesse
   * modo o Playwright termina a rodada e SOBE UM SERVIDOR HTTP para exibir o
   * relatório — fica vivo até alguém fechá-lo. O sintoma era exatamente o que a
   * auditoria descreveu: 16 testes alcançados, nenhuma falha de asserção, e o
   * processo sem encerrar em 300 s. O `playwright.shots.config.ts`, com a MESMA
   * configuração de `webServer`, nunca travou — porque usa `reporter: 'line'`.
   *
   * `list` junto para a rodada continuar legível no terminal; o HTML fica
   * gravado em disco e é aberto à mão com `npx playwright show-report`.
   */
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
    /*
     * Só nos testes, e sem uma linha de mudança no app: o `index.css` já traz o
     * bloco `@media (prefers-reduced-motion: reduce)` que zera
     * `animation-duration` e `transition-duration` de tudo. Isto liga essa
     * mídia no navegador da suíte.
     *
     * É o que permitiu trocar treze `waitForTimeout` do `mobile_layout` (mais
     * de 25 s de sono por rodada) por espera determinística. O portão continua
     * medindo o mesmo estado — o comentário do próprio teste dizia que só
     * interessa a tela PARADA, e dormir era uma forma cara e incerta de chegar
     * nela.
     */
    reducedMotion: 'reduce',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
      // Sem isto o projeto desktop rodaria também os specs de mobile, num
      // viewport onde a barra inferior está escondida por `md:hidden` — os
      // seletores não achariam nada e a falha diria "elemento ausente" em vez de
      // "este spec não é para cá".
      testIgnore: /.*\.mobile\.spec\.ts/,
    },
    // Projeto MOBILE. A barra inferior e o FAB "Nova despesa" vivem atrás de
    // `md:hidden`, então nada em viewport desktop os alcança — e era exatamente
    // aí que estava o defeito que a auditoria encontrou: o FAB aparecia na visão
    // global e lançava despesa no último workspace visitado, invisível para o
    // usuário. A suíte de acessibilidade AFIRMAVA que `/overview` é somente
    // leitura, testando só o desktop, onde o botão nem é renderizado.
    {
      name: 'mobile',
      use: { ...devices['Pixel 5'] },
      testMatch: /.*\.mobile\.spec\.ts/,
    },
  ],
  /*
   * `undefined` quando os servidores são externos: é assim que `npm run test:e2e`
   * (`scripts/e2e.mjs`) fica sendo o ÚNICO dono do ciclo de vida. Com os dois
   * donos, o Playwright tentaria subir na porta já ocupada.
   *
   * O bloco abaixo continua existindo para quem chama `npx playwright test`
   * direto — o CI de Linux fazia exatamente isso e nunca teve o problema.
   */
  webServer: SERVIDORES_EXTERNOS ? undefined : [
    {
      // Executável PURO, sem `&&`: com encadeamento o Playwright sobe um shell e
      // não consegue encerrar o uvicorn no Windows. A limpeza do e2e.db roda no
      // CORPO deste módulo (ver o topo do arquivo) — `globalSetup` não serve,
      // porque corre DEPOIS do `webServer` e o backend já teria aberto o banco.
      command: `${PYTHON} -m uvicorn app.main:app --port 8000`,
      cwd: '../backend',
      url: 'http://localhost:8000/api/v1/health',
      // NUNCA reutilizar: com `true`, um uvicorn de desenvolvimento já ligado na
      // 8000 era adotado pelo Playwright — e esse processo está conectado ao
      // `dev.db`. O `env` abaixo só vale para o processo que o Playwright SOBE,
      // então a suíte passava a cadastrar usuários e lançar despesas no banco de
      // desenvolvimento. O comentário dizia "banco descartável"; a configuração
      // não garantia isso.
      reuseExistingServer: false,
      timeout: 60_000,
      // A suíte registra vários usuários em sequência — o rate limit de auth
      // derrubaria os specs; a proteção em si tem testes no backend (e a suíte
      // `e2e-prod` a exercita ligada, contra o stack real).
      env: {
        RATE_LIMIT_ENABLED: 'False',
        DATABASE_URL: 'sqlite:///./e2e.db',
        // Janela de bootstrap para o spec de a11y alcançar /admin (ver e2e.mjs).
        SUPERADMIN_EMAIL: 'admin-a11y@e2e.com',
      },
    },
    {
      // `node` no script do vite, e não `npm run dev` NEM `npx vite`: os dois são
      // wrappers que sobem o vite como processo NETO, e no Windows matar o
      // wrapper não leva a árvore junto. A versão anterior trocou `npm` por
      // `npx` acreditando ter resolvido — `npx` é ele próprio um script Node, e
      // o `.bin/vite` do Windows é um `.cmd`, que traz um shell junto. O único
      // que não interpõe processo é chamar o entrypoint direto.
      //
      // `reuseExistingServer: false` também aqui: adotar um `npm run dev` local
      // é adotar um processo que o Playwright não consegue encerrar, o que
      // reintroduz o mesmo travamento por outro caminho.
      command: 'node ./node_modules/vite/bin/vite.js --port 5173 --strictPort',
      url: 'http://localhost:5173',
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
