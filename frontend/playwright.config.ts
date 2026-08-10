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

/*
 * Apaga o banco descartável antes da rodada.
 *
 * Isto morava no `command` do `webServer`, encadeado com `&&`
 * (`if exist e2e.db del /f /q e2e.db && python -m uvicorn ...`). O encadeamento
 * obriga o Playwright a subir um SHELL, e o uvicorn vira NETO do processo que
 * ele controla — no Windows, matar o shell não leva a árvore junto. O efeito era
 * `npx playwright test` terminar os testes e ficar vivo por 240–300 s até o
 * timeout: os specs passavam e o comando não devolvia o terminal.
 *
 * Aqui e não num `globalSetup`: o Playwright sobe o `webServer` ANTES de rodar o
 * globalSetup, então lá o backend já abriu o arquivo e o `rm` falha com EPERM no
 * Windows. O corpo do módulo de config é avaliado antes de qualquer processo ser
 * criado, que é exatamente a janela necessária.
 */
const E2E_DB = path.resolve(import.meta.dirname, '..', 'backend', 'e2e.db');
// Só no processo PRINCIPAL: o Playwright reimporta a config em cada worker, e lá
// o backend já está de pé com o arquivo aberto — apagar de novo falharia com
// EPERM no Windows (e, pior, apagaria o banco no meio da rodada em outros SOs).
// `TEST_WORKER_INDEX` só existe nos workers.
if (process.env.TEST_WORKER_INDEX === undefined) {
  // `-wal`/`-shm` junto: sem eles o SQLite reconstrói o estado recém-apagado.
  for (const arquivo of [E2E_DB, `${E2E_DB}-wal`, `${E2E_DB}-shm`]) {
    fs.rmSync(arquivo, { force: true });
  }
}

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false, // specs compartilham o backend; serial evita corrida
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: 'html',
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
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
  webServer: [
    {
      // Executável PURO, sem `&&`: com encadeamento o Playwright sobe um shell e
      // não consegue encerrar o uvicorn no Windows. A limpeza do e2e.db mudou-se
      // para o `globalSetup` por causa disso.
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
      // (5/min) derrubaria os specs; a proteção em si tem testes no backend.
      env: { RATE_LIMIT_ENABLED: 'False', DATABASE_URL: 'sqlite:///./e2e.db' },
    },
    {
      command: 'npm run dev',
      url: 'http://localhost:5173',
      reuseExistingServer: !process.env.CI,
    },
  ],
});
