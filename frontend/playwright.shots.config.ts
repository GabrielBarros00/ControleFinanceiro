import { defineConfig, devices } from '@playwright/test';
import path from 'node:path';

// Mesmo motivo (e mesmo cuidado com o cmd.exe) do playwright.config.ts.
// `import.meta.dirname` (não `__dirname`): o package é `"type": "module"`.
const VENV_PYTHON = path.resolve(
  import.meta.dirname,
  '..',
  '.venv',
  process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
);
const PYTHON = JSON.stringify(process.env.E2E_PYTHON ?? VENV_PYTHON);

export default defineConfig({
  testDir: './e2e-shots',
  fullyParallel: false,
  workers: 1,
  reporter: 'line',
  use: {
    baseURL: 'http://localhost:5173',
    viewport: { width: 1440, height: 900 },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `${PYTHON} -m uvicorn app.main:app --port 8000`,
      cwd: '../backend',
      url: 'http://localhost:8000/api/v1/health',
      reuseExistingServer: true,
      timeout: 60_000,
      // Banco descartável e rate limit desligado (roteiro registra usuário).
      env: { RATE_LIMIT_ENABLED: 'False', DATABASE_URL: 'sqlite:///./shots.db' },
    },
    {
      // `node` no script do vite pelo mesmo motivo do config principal: `npm run
      // dev` e `npx` deixam o vite como processo neto e o runner não encerra no
      // Windows.
      //
      // `reuseExistingServer: true` aqui é DELIBERADO e diverge do config
      // principal: gerar telas é um roteiro de leitura contra um banco próprio
      // (`shots.db`), sem cadastro nem escrita que possa contaminar o `dev.db`.
      // O risco que motivou o `false` lá — a suíte escrever no banco de
      // desenvolvimento — não existe aqui, e reaproveitar o servidor já ligado
      // torna `npm run shots` instantâneo.
      command: 'node ./node_modules/vite/bin/vite.js --port 5173 --strictPort',
      url: 'http://localhost:5173',
      reuseExistingServer: true,
    },
  ],
});
