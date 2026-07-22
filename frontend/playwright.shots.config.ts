import { defineConfig, devices } from '@playwright/test';

/**
 * Config dedicada ao roteiro de CAPTURA DE TELAS (docs/frontend-redesign).
 * Fica fora da suíte e2e normal (testDir próprio) para não deixar o
 * `npm run test:e2e` lento. Sobe backend (SQLite descartável, sem rate limit)
 * e o dev server, igual à config e2e.
 *
 *   npm run shots            # ou: npx playwright test --config=playwright.shots.config.ts
 *   -> frontend/screenshots/*.png
 */
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
      command: 'python -m uvicorn app.main:app --port 8000',
      cwd: '../backend',
      url: 'http://localhost:8000/api/v1/health',
      reuseExistingServer: true,
      timeout: 60_000,
      // Banco descartável e rate limit desligado (roteiro registra usuário).
      env: { RATE_LIMIT_ENABLED: 'False', DATABASE_URL: 'sqlite:///./shots.db' },
    },
    {
      command: 'npm run dev',
      url: 'http://localhost:5173',
      reuseExistingServer: true,
    },
  ],
});
