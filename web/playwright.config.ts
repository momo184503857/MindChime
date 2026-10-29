import { defineConfig, devices } from '@playwright/test';
import path from 'node:path';
process.env.PLAYWRIGHT_BROWSERS_PATH ||= path.resolve('.cache/ms-playwright');
export default defineConfig({
  testDir: './tests/e2e',
  timeout: 60000,
  expect: { timeout: 15000 },
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: process.env.MINDCHIME_WEB_URL || 'http://127.0.0.1:5173',
    viewport: { width: 1440, height: 1000 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  reporter: [['list'], ['json', { outputFile: 'test-results/results.json' }]],
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1000 } },
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'], viewport: { width: 1440, height: 1000 } },
    },
    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'], viewport: { width: 1440, height: 1000 } },
    },
  ],
});
