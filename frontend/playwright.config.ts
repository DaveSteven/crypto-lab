import { defineConfig } from '@playwright/test'

// E2E runs against the real local backend with a test database and the
// exchange feed disabled (see docs/11 §12). Browsers are installed on
// demand with `pnpm exec playwright install`.
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  use: {
    baseURL: 'http://127.0.0.1:5173',
    headless: true,
  },
  webServer: {
    command: 'pnpm dev --port 5173 --strictPort',
    url: 'http://127.0.0.1:5173',
    reuseExistingServer: true,
    timeout: 30_000,
  },
})
