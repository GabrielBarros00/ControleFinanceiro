import { defineConfig, devices } from '@playwright/test';
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

// Apaga o banco descartável antes de cada rodada. `del` no cmd.exe, `rm -f` no
// resto; ambos com o "não falhe se não existir", porque a primeira rodada numa
// máquina limpa não tem o arquivo.
const DELETA_E2E_DB =
  process.platform === 'win32'
    ? 'if exist e2e.db del /f /q e2e.db &&'
    : 'rm -f e2e.db &&';

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
      // `rm -f e2e.db` antes de subir: o banco é descartável POR DEFINIÇÃO, e um
      // resíduo da rodada anterior (usuário já cadastrado, workspace com nome
      // repetido) faz specs falharem por motivo que não é o código.
      command: `${DELETA_E2E_DB} ${PYTHON} -m uvicorn app.main:app --port 8000`,
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
