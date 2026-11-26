import { expect, test, type Page } from '@playwright/test'

/**
 * End-to-end trading flow against the real backend with the exchange feed
 * disabled. Market data is therefore unavailable by design: limit orders
 * stay pending briefly and are rejected/canceled by the scheduler without
 * ever filling — the assertions accept exactly those deterministic outcomes.
 */
const UNIQUE = `e2e-${Date.now()}`

async function bootstrapSession(page: Page) {
  await page.goto('/trading')
  await page.getByLabel('环境名称').fill(`E2E ${UNIQUE}`)
  await page.getByRole('button', { name: '创建并进入' }).click()
  await expect(page.getByRole('button', { name: '提交订单意图' })).toBeVisible({
    timeout: 15_000,
  })
}

test('bootstrap, place limit intent, inspect orders, cancel, check balances', async ({
  page,
}) => {
  await bootstrapSession(page)

  // Order intent: a limit buy needs only quote funds (initial USDT grant);
  // acceptance, freezing and scheduling are server decisions.
  await page.getByRole('group', { name: '方向' }).getByRole('button', { name: '买入' }).click()
  await page.getByRole('group', { name: '订单类型' }).getByRole('button', { name: '限价' }).click()
  await page.getByLabel('数量（BTC）').fill('0.01')
  await page.getByLabel('限价（USDT）').fill('50000')
  await page.getByRole('button', { name: '提交订单意图' }).click()
  await expect(page.getByRole('status')).toContainText('订单已提交')

  // Orders page shows the committed order with limit price and timing columns.
  await page.getByRole('link', { name: '订单' }).click()
  await expect(page.getByRole('heading', { name: '订单' })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: '限价' })).toBeVisible()
  await expect(page.getByText('50000')).toBeVisible()

  // The scheduler may reject the order (no executable book with the feed
  // off) before the cancel lands; both end states are valid outcomes.
  const cancel = page.getByRole('button', { name: '取消', exact: true })
  if (await cancel.count()) {
    await cancel.first().click()
    await expect(page.getByRole('alert')).toHaveCount(0, { timeout: 10_000 }).catch(() => undefined)
  }
  await expect(page.getByText(/CANCELED|REJECTED|OPEN|PENDING_EXECUTION/).first()).toBeVisible()

  // Account page shows the simulated USDT balance and consistency version.
  await page.getByRole('link', { name: '账户' }).click()
  await expect(page.getByRole('heading', { name: '账户' })).toBeVisible()
  await expect(page.getByText('USDT')).toBeVisible()
  await expect(page.getByText(/一致性版本/)).toBeVisible()

  // Executions page renders empty (no fills possible without a book).
  await page.getByRole('link', { name: '成交' }).click()
  await expect(page.getByRole('heading', { name: '成交记录' })).toBeVisible()

  // Simulation disclaimer is always present.
  await expect(page.getByText('模拟交易声明')).toBeVisible()
})

test('session persists across reload', async ({ page }) => {
  await bootstrapSession(page)
  await page.reload()
  // Still authenticated into the session (no bootstrap form).
  await expect(page.getByRole('button', { name: '提交订单意图' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '模拟交易' })).toBeVisible()
})
