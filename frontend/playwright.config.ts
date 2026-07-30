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
    },
  ],
  webServer: [
    {
      command: `${PYTHON} -m uvicorn app.main:app --port 8000`,
      cwd: '../backend',
      url: 'http://localhost:8000/api/v1/health',
      reuseExistingServer: true,
      timeout: 60_000,
      // A suíte registra vários usuários em sequência — o rate limit de auth
      // (5/min) derrubaria os specs; a proteção em si tem testes no backend.
      // Banco DESCARTÁVEL (e2e.db): o E2E nunca escreve no dev.db — o startup
      // em dev roda `alembic upgrade head` e cria o schema sozinho.
      env: { RATE_LIMIT_ENABLED: 'False', DATABASE_URL: 'sqlite:///./e2e.db' },
    },
    {
      command: 'npm run dev',
      url: 'http://localhost:5173',
      reuseExistingServer: !process.env.CI,
    },
  ],
});
