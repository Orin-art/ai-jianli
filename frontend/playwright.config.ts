import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './tests', workers: 1, timeout: 45000,
  use: { baseURL: process.env.E2E_URL || 'http://127.0.0.1:15173', viewport: { width: 1440, height: 1000 }, screenshot: 'only-on-failure', trace: 'retain-on-failure', launchOptions: { executablePath: process.env.E2E_CHROMIUM || undefined } },
  reporter: 'list',
})
