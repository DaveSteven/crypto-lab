import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'

/**
 * Task 1.12.12 acceptance: confirmation flow with real fills and balance changes,
 * market-failure gating, layout persistence, environment switching, the desktop
 * viewport matrix, accessibility and performance. The feed is the SYNTHETIC
 * scripted one (tests/support/e2e_server.py).
 */
const CONTROL = process.env.CRYPTO_LAB_E2E_FEED_CONTROL ?? '/tmp/crypto-lab-e2e-feed-control'
const SHOTS = '../docs/screenshots/acceptance'
const UNIQUE = `acc-${Date.now()}`

test.afterEach(() => rmSync(CONTROL, { force: true }))

async function bootstrap(page: Page, label: string) {
  await page.goto('/trading')
  await page.getByLabel('环境名称').fill(`${label} ${UNIQUE}`)
  await page.getByRole('button', { name: '创建并进入' }).click()
  await expect(page.getByRole('button', { name: '买入提交' })).toBeVisible({ timeout: 15_000 })
  // Trading is enabled only once the account snapshot AND a valid book exist.
  await expect(page.getByRole('button', { name: '买入提交' })).toBeEnabled({ timeout: 15_000 })
}

async function marketBuy(page: Page, quantity: string, budget: string) {
  await page.getByLabel('数量（BTC）').fill(quantity)
  await page.getByLabel('最大报价预算（USDT，含手续费）').fill(budget)
  await page.getByRole('combobox', { name: /模拟执行延迟/ }).selectOption('IDEAL')
  await page.getByRole('button', { name: '买入提交' }).click()
  const dialog = page.getByRole('dialog', { name: '确认下单' })
  await expect(dialog).toContainText('本地参考估算')
  await dialog.getByRole('button', { name: '确认提交' }).click()
}

test('confirmation flow: order is filled, balances and activity tabs reflect it', async ({ page }) => {
  await bootstrap(page, 'fill')
  await marketBuy(page, '0.01', '700')
  await expect(page.getByRole('status').filter({ hasText: '订单已提交' })).toBeVisible()

  await page.getByRole('tab', { name: '历史订单' }).click()
  await expect(page.getByText('全部成交')).toBeVisible({ timeout: 15_000 })

  await page.getByRole('tab', { name: '成交记录' }).click()
  await expect(page.getByRole('row').filter({ hasText: '买入' })).toHaveCount(1)

  await page.getByRole('tab', { name: '资产余额' }).click()
  await expect(page.getByRole('row').filter({ hasText: 'BTC' })).toContainText('0.01')
  // Synthetic Ask is 60000.5 + 0.1% fee: 600.005 + 0.600005 leaves < 10000 USDT.
  const usdt = await page.getByRole('row').filter({ hasText: 'USDT' }).innerText()
  expect(Number(usdt.match(/(\d+(?:\.\d+)?)/)?.[1])).toBeLessThan(10_000)

  await page.getByRole('tab', { name: '成交记录' }).click()
  await page.getByRole('button', { name: '详情' }).first().click()
  const drawer = page.getByRole('dialog', { name: '订单与成交详情' })
  await expect(drawer).toContainText('全部成交')
  await page.keyboard.press('Escape')
  await expect(drawer).toHaveCount(0)
})

test('feed failure disables trading with a reason and recovers automatically', async ({ page }) => {
  await bootstrap(page, 'stale')
  writeFileSync(CONTROL, 'drop')
  await expect(page.getByRole('alert').filter({ hasText: '下单已暂停' })).toBeVisible({ timeout: 20_000 })
  await expect(page.getByRole('button', { name: '买入提交' })).toBeDisabled()
  rmSync(CONTROL, { force: true })
  await expect(page.getByRole('button', { name: '买入提交' })).toBeEnabled({ timeout: 30_000 })
})

test('panel layout is persisted across reloads', async ({ page }) => {
  await bootstrap(page, 'layout')
  const handle = page.getByRole('separator').first()
  await handle.focus()
  for (let i = 0; i < 6; i += 1) await page.keyboard.press('ArrowRight')
  await page.waitForTimeout(600) // layout autosave is debounced
  const read = () =>
    page.evaluate(() =>
      Object.fromEntries(
        Object.entries(localStorage).filter(([key]) => key.startsWith('react-resizable-panels:trading-main')),
      ),
    )
  const before = await read()
  expect(Object.keys(before).length).toBeGreaterThan(0)
  await page.reload()
  await expect(page.getByRole('button', { name: '买入提交' })).toBeVisible({ timeout: 15_000 })
  expect(await read()).toEqual(before)
})

test('environment switching isolates orders, balances and cache', async ({ page }) => {
  await bootstrap(page, 'envA')
  await marketBuy(page, '0.01', '700')
  await page.getByRole('tab', { name: '历史订单' }).click()
  await expect(page.getByText('全部成交')).toBeVisible({ timeout: 15_000 })

  await page.getByRole('link', { name: '设置' }).click()
  await page.getByLabel('新环境名称').fill(`envB ${UNIQUE}`)
  await page.getByRole('button', { name: '创建并切换' }).click()

  await page.getByRole('link', { name: '总览' }).click()
  await expect(page.getByTestId('total-assets')).toContainText('10000 USDT', { timeout: 15_000 })
  await expect(page.getByText('暂无成交。')).toBeVisible()

  await page.getByRole('combobox', { name: '当前模拟环境' }).selectOption({ label: `envA ${UNIQUE}` })
  await expect(page.getByText('暂无成交。')).toHaveCount(0, { timeout: 15_000 })
  await expect(page.getByTestId('total-assets')).not.toContainText('10000 USDT', { timeout: 15_000 })
})

const VIEWPORTS = [
  { width: 1280, height: 720 },
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
  { width: 2560, height: 1440 },
]

for (const viewport of VIEWPORTS) {
  test(`desktop matrix ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport)
    await bootstrap(page, `vp${viewport.width}`)
    for (const path of ['/trading', '/overview', '/markets', '/settings']) {
      await page.goto(path)
      await expect(page.getByRole('navigation', { name: '主导航' })).toBeVisible()
      const overflow = await page.evaluate(() => ({
        x: document.documentElement.scrollWidth - window.innerWidth,
        y: document.documentElement.scrollHeight - window.innerHeight,
      }))
      expect(overflow.x, `${path} must not scroll horizontally`).toBeLessThanOrEqual(0)
      expect(overflow.y, `${path} must fit the viewport height (panels scroll internally)`).toBeLessThanOrEqual(0)
    }
    await page.goto('/trading')
    // Live data present before judging the layout (and before the evidence screenshot).
    await expect(page.getByTestId('order-book')).toBeVisible({ timeout: 15_000 })
    await expect(page.getByRole('button', { name: '买入提交' })).toBeEnabled({ timeout: 15_000 })
    for (const name of ['买入提交', '买入', '卖出']) {
      const target = page.getByRole('button', { name, exact: true }).first()
      const box = await target.boundingBox()
      expect(box, name).not.toBeNull()
      expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width)
      expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height)
      // Not merely inside the viewport: the control must be the topmost element at its
      // centre, i.e. actually reachable without scrolling or being clipped by a panel.
      const reachable = await target.evaluate((element) => {
        const rect = element.getBoundingClientRect()
        const hit = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2)
        return hit !== null && (hit === element || element.contains(hit))
      })
      expect(reachable, `${name} must be reachable without scrolling`).toBe(true)
    }
    mkdirSync(SHOTS, { recursive: true })
    await page.screenshot({ path: `${SHOTS}/trading-${viewport.width}x${viewport.height}.jpg`, type: 'jpeg', quality: 60 })
  })
}

test('below the minimum width a concise desktop-only notice is shown', async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 768 })
  await page.goto('/trading')
  await expect(page.getByText(/最小支持视口宽度|1280/)).toBeVisible()
})

async function unnamedControls(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const name = (el: Element): string => {
      const aria = el.getAttribute('aria-label')?.trim()
      if (aria) return aria
      const labelledby = el.getAttribute('aria-labelledby')
      if (labelledby) {
        const text = labelledby.split(' ').map((id) => document.getElementById(id)?.textContent ?? '').join(' ').trim()
        if (text) return text
      }
      const id = el.getAttribute('id')
      if (id) {
        const label = document.querySelector(`label[for="${id}"]`)
        if (label?.textContent?.trim()) return label.textContent.trim()
      }
      if (el.closest('label')?.textContent?.trim()) return el.closest('label')!.textContent!.trim()
      if (el.textContent?.trim()) return el.textContent.trim()
      return (el.getAttribute('title') ?? el.getAttribute('placeholder') ?? '').trim()
    }
    const selector = 'button, a[href], input, select, textarea, [role="tab"], [role="separator"][tabindex]'
    return [...document.querySelectorAll(selector)]
      .filter((el) => !(el instanceof HTMLInputElement && el.type === 'hidden'))
      .filter((el) => (el as HTMLElement).offsetParent !== null)
      .filter((el) => name(el) === '')
      .map((el) => el.outerHTML.slice(0, 120))
  })
}

test('accessibility: names, landmarks, dialog focus management, keyboard reachability', async ({ page }) => {
  await bootstrap(page, 'a11y')
  expect(await page.locator('html').getAttribute('lang')).toBeTruthy()
  for (const path of ['/trading', '/overview', '/markets', '/settings']) {
    await page.goto(path)
    await expect(page.getByRole('navigation', { name: '主导航' })).toBeVisible()
    await expect(page.locator('main')).toHaveCount(1)
    expect(await unnamedControls(page), `${path}: controls without an accessible name`).toEqual([])
  }

  await page.goto('/trading')
  await page.getByLabel('数量（BTC）').fill('0.01')
  await page.getByLabel('最大报价预算（USDT，含手续费）').fill('700')
  const submit = page.getByRole('button', { name: '买入提交' })
  await expect(submit).toBeEnabled({ timeout: 15_000 }) // snapshot + valid book after the reload
  await submit.focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog', { name: '确认下单' })
  await expect(dialog).toBeVisible()
  await expect(dialog).toHaveAttribute('aria-modal', 'true')
  expect(await page.evaluate(() => document.activeElement?.getAttribute('role'))).toBe('dialog')
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(submit).toBeFocused() // focus returns to the trigger

  // Keyboard-only path to the trading controls.
  await page.locator('body').focus()
  const reached = new Set<string>()
  for (let i = 0; i < 60; i += 1) {
    await page.keyboard.press('Tab')
    reached.add(await page.evaluate(() => document.activeElement?.textContent?.trim().slice(0, 20) ?? ''))
  }
  expect([...reached].join('|')).toContain('买入提交')
})

test('performance: no long main-thread stalls, bounded heap and DOM during live feed', async ({ page }, testInfo) => {
  await bootstrap(page, 'perf')
  await page.evaluate(() => {
    ;(window as unknown as { __longTasks: number[] }).__longTasks = []
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) (window as unknown as { __longTasks: number[] }).__longTasks.push(entry.duration)
    }).observe({ entryTypes: ['longtask'] })
  })
  const cdp = await page.context().newCDPSession(page)
  await cdp.send('Performance.enable')
  const sample = async () => {
    await cdp.send('HeapProfiler.collectGarbage') // compare live heap, not allocation noise
    const metrics = await cdp.send('Performance.getMetrics')
    return {
      heap: metrics.metrics.find((metric) => metric.name === 'JSHeapUsedSize')?.value ?? 0,
      nodes: await page.evaluate(() => document.getElementsByTagName('*').length),
    }
  }
  const start = await sample()
  await page.waitForTimeout(20_000) // 1 ticker + 1 book update per second per instrument
  const end = await sample()
  const longTasks = await page.evaluate(() => (window as unknown as { __longTasks: number[] }).__longTasks)
  const totalLong = longTasks.reduce((a, b) => a + b, 0)
  const result = {
    longTaskCount: longTasks.length,
    longTaskTotalMs: Math.round(totalLong),
    longestMs: Math.round(Math.max(0, ...longTasks)),
    heapGrowthMB: Number(((end.heap - start.heap) / 1_048_576).toFixed(2)),
    domNodesStart: start.nodes,
    domNodesEnd: end.nodes,
  }
  testInfo.annotations.push({ type: 'perf', description: JSON.stringify(result) })
  console.log('PERF', JSON.stringify(result))
  expect(result.longTaskTotalMs).toBeLessThan(1_000)
  expect(result.longestMs).toBeLessThan(200)
  expect(Math.abs(end.nodes - start.nodes)).toBeLessThan(200)
  expect(result.heapGrowthMB).toBeLessThan(40)
})
