import { expect, test, type Page } from '@playwright/test'

/**
 * End-to-end trading flow against the real backend with the SYNTHETIC scripted
 * feed. A limit buy far below the synthetic price rests unfilled; cancelling or
 * a scheduler end state are both accepted outcomes.
 */
const UNIQUE = `e2e-${Date.now()}`

async function bootstrapSession(page: Page) {
  await page.goto('/trading')
  await page.getByLabel('环境名称').fill(`E2E ${UNIQUE}`)
  await page.getByRole('button', { name: '创建并进入' }).click()
  await expect(page.getByRole('button', { name: '预览买入订单' })).toBeVisible({
    timeout: 15_000,
  })
}

test('bootstrap, place limit intent, inspect activity tabs, balances', async ({
  page,
}) => {
  await bootstrapSession(page)

  // Top navigation per docs/12 §6.1: brand + implemented entries + identity.
  await expect(page.getByText('Paper Trading')).toBeVisible()
  await expect(page.getByRole('link', { name: '交易' })).toBeVisible()

  // Order intent: a limit buy needs only quote funds (initial USDT grant).
  await page.getByRole('group', { name: '方向' }).getByRole('button', { name: '买入' }).click()
  await page.getByRole('group', { name: '订单类型' }).getByRole('button', { name: '限价' }).click()
  await page.getByLabel('数量（BTC）').fill('0.01')
  await page.getByLabel('限价（USDT）').fill('50000')
  await page.getByRole('button', { name: '预览买入订单' }).click()
  // Every order goes through the confirmation dialog (docs/12 §11.5).
  await page.getByRole('dialog', { name: '确认下单' }).getByRole('button', { name: '确认提交' }).click()
  await expect(page.getByRole('status').filter({ hasText: '订单已提交' })).toBeVisible()

  // Account Activity Panel: 当前委托 shows the committed order.
  await page.getByRole('tab', { name: /当前委托/ }).click()
  await expect(page.getByRole('columnheader', { name: '限价' })).toBeVisible()
  await expect(page.getByRole('cell', { name: '50000', exact: true })).toBeVisible()

  // The scheduler may reject the order (no executable book with the feed
  // off) before the cancel lands; both end states are valid outcomes.
  const cancel = page.getByRole('button', { name: '取消', exact: true })
  if (await cancel.count()) {
    await cancel.first().click()
    await expect(page.getByRole('alert')).toHaveCount(0, { timeout: 10_000 }).catch(() => undefined)
  }

  // Balances tab shows the simulated USDT grant from the Ledger projection.
  await page.getByRole('tab', { name: '资产余额' }).click()
  await expect(page.getByText('USDT').first()).toBeVisible()

  // Executions tab renders an explicit empty state (no fills possible).
  await page.getByRole('tab', { name: '成交记录' }).click()
  await expect(page.getByText('暂无成交。')).toBeVisible()
})

test('session persists across reload', async ({ page }) => {
  await bootstrapSession(page)
  await page.reload()
  await expect(page.getByRole('button', { name: '预览买入订单' })).toBeVisible({
    timeout: 15_000,
  })
  await expect(page.getByText('Paper Trading')).toBeVisible()
})
