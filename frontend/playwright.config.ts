import { defineConfig, devices } from '@playwright/test';

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
      command: 'python -m uvicorn app.main:app --port 8000',
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
