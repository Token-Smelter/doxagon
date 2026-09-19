import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  // Presentation specs launch a real backend per worker. CPU-based defaults
  // overcommit this host and turn resource contention into test failures.
  workers: 4,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  expect: { timeout: 15_000 },
  reporter: 'list',
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173',
    // Local runs have no retries, so record the first failure as well.
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: 'npm run dev -- --port 5173 --strictPort',
    env: { DOXAGON_E2E: '1' },
    url: 'http://localhost:5173',
    // An existing dev server may serve another checkout. Fail on a busy port
    // instead of accepting browser evidence for the wrong source tree.
    reuseExistingServer: false,
    timeout: 120 * 1000,
  },
});
