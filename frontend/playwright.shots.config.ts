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
      //
      // `REGISTRATION_MODE=open` porque o roteiro SEMEIA os dados criando uma
      // conta, e desde o ADR 0026 o cadastro nasce por convite: sem isto o
      // `/auth/register` devolve 403 e a captura morre antes da primeira tela.
      // Ficou quebrado desde que o portão entrou — ninguém executa este roteiro
      // no CI, então nada avisou. Abrir aqui não afrouxa nada: o servidor é
      // local, efêmero e escreve num `shots.db` descartável.
      //
      // `SUPERADMIN_EMAIL` precisa casar com o `email` do roteiro: é o que faz a
      // conta nascer superadministradora e torna `/admin` alcançável. Sem isto,
      // a captura da área administrativa sairia como tela de erro.
      env: {
        RATE_LIMIT_ENABLED: 'False',
        DATABASE_URL: 'sqlite:///./shots.db',
        REGISTRATION_MODE: 'open',
        SUPERADMIN_EMAIL: 'demo@cf4.app',
      },
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
