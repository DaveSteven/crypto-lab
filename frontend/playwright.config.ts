import { defineConfig } from '@playwright/test'

/**
 * E2E against the real local backend with the isolated test database and
 * the exchange feed disabled (docs/11 §12): deterministic, no external
 * network. Requires CRYPTO_LAB_TEST_DATABASE_URL in the environment.
 */
const testDatabaseUrl = process.env.CRYPTO_LAB_TEST_DATABASE_URL

export default defineConfig({
  testDir: './e2e',
  timeout: 45_000,
  use: {
    baseURL: 'http://127.0.0.1:5173',
    headless: true,
  },
  webServer: [
    {
      command: '.venv/bin/python -m crypto_lab.api',
      cwd: '..',
      url: 'http://127.0.0.1:8642/health/ready',
      reuseExistingServer: true,
      timeout: 30_000,
      env: {
        CRYPTO_LAB_DATABASE_URL: testDatabaseUrl ?? '',
        CRYPTO_LAB_FEED_ENABLED: 'false',
      },
    },
    {
      command: 'pnpm dev --port 5173 --strictPort',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: true,
      timeout: 30_000,
    },
  ],
})
