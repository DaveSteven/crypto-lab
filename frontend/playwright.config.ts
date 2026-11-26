import { defineConfig } from '@playwright/test'

/**
 * Browser E2E against the real backend app and the isolated test database, with
 * a SYNTHETIC scripted exchange feed (tests/support/e2e_server.py): the whole
 * market pipeline (feed -> dispatcher -> engine -> WS) runs for real, but no
 * external network is used and prices are deterministic test data.
 * Requires CRYPTO_LAB_TEST_DATABASE_URL; the server refuses non-test databases.
 */
const testDatabaseUrl = process.env.CRYPTO_LAB_TEST_DATABASE_URL

export default defineConfig({
  testDir: './e2e',
  timeout: 45_000,
  // One shared backend and scripted feed: the feed-failure test cuts the feed for everyone,
  // so tests must not run in parallel.
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:5173',
    headless: true,
  },
  webServer: [
    {
      command: '.venv/bin/python tests/support/e2e_server.py',
      cwd: '..',
      url: 'http://127.0.0.1:8642/health/ready',
      reuseExistingServer: true,
      timeout: 30_000,
      env: {
        PYTHONPATH: 'src',
        CRYPTO_LAB_DATABASE_URL: testDatabaseUrl ?? '',
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
