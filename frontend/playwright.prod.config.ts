import { defineConfig, devices } from '@playwright/test';

// Roda contra o stack Docker Compose já em pé (nginx + backend production).
// Uso: npx playwright test --config playwright.prod.config.ts
//      E2E_BASE_URL=http://host:porta para outro deploy.
export default defineConfig({
  testDir: './e2e-prod',
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:8890',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
