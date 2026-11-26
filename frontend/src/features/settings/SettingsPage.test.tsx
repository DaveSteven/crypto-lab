import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { MemoryRouter } from 'react-router-dom'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, test, vi } from 'vitest'
import { SettingsPage } from './SettingsPage'
import { gateway } from '@/app/gateway'
import { useSessionStore } from '@/app/sessionStore'

const server = setupServer()
beforeAll(() => server.listen())
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

const env = (id: string, name: string) => ({
  environment_id: id,
  name,
  status: 'ACTIVE',
  created_ts_ms: 1,
  updated_ts_ms: 1,
})

beforeEach(() => {
  vi.spyOn(gateway, 'stop').mockImplementation(() => undefined)
  useSessionStore.getState().setSession({ environmentId: 'env-1', accountId: 'a-1' })
  localStorage.clear()
  server.use(
    http.get('*/api/v1/environments', () =>
      HttpResponse.json({ items: [env('env-1', '主环境'), env('env-2', '实验环境')] }),
    ),
    http.get('*/api/v1/environments/:id/accounts', ({ params }) =>
      HttpResponse.json({
        items: [{ account_id: `a-of-${String(params.id)}`, exchange_id: 'okx', name: 'Paper', created_ts_ms: 1 }],
      }),
    ),
    http.get('*/health/ready', () => HttpResponse.json({ status: 'ready' })),
    http.get('*/health/recovery', () =>
      HttpResponse.json({ recovered: ['env-1'], failed: { 'env-2': 'RuntimeError: boom' } }),
    ),
    http.get('*/api/v1/market/instruments', () =>
      HttpResponse.json({
        feed_enabled: true,
        items: [{ instrument_id: 'okx:SPOT:BTC/USDT', exchange_id: 'okx', market_type: 'SPOT', base_asset: 'BTC', quote_asset: 'USDT' }],
      }),
    ),
  )
})

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('SettingsPage', () => {
  test('lists environments, marks the current one and switches to another', async () => {
    const user = userEvent.setup()
    renderPage()
    expect(await screen.findByText('当前环境')).toBeVisible()
    await user.click(await screen.findByRole('button', { name: '切换到此环境' }))
    await waitFor(() =>
      expect(useSessionStore.getState().session).toEqual({ environmentId: 'env-2', accountId: 'a-of-env-2' }),
    )
  })

  test('states honestly what the backend does not provide', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(await screen.findByRole('button', { name: '账户配置' }))
    expect(await screen.findByText(/默认执行延迟/)).toBeVisible()
    expect(screen.getByText(/尚未实现账户级持久化/)).toBeVisible()
    await user.click(screen.getByRole('button', { name: '模拟环境' }))
    expect(screen.getByText(/不提供删除或重置环境/)).toBeVisible()
  })

  test('shows system status including a failed environment recovery', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(await screen.findByRole('button', { name: '系统状态' }))
    expect(await screen.findByText('就绪')).toBeVisible()
    expect(await screen.findByText('1 个环境恢复失败')).toBeVisible()
    expect(screen.getByText(/env-2：RuntimeError: boom/)).toBeVisible()
    expect(screen.getByText('BTC/USDT')).toBeVisible()
  })

  test('restoring the default layout clears only saved panel layouts', async () => {
    const user = userEvent.setup()
    localStorage.setItem('react-resizable-panels:trading-workspace.v1', '{}')
    localStorage.setItem('crypto-lab.session', '{}')
    renderPage()
    await user.click(await screen.findByRole('button', { name: '工作区' }))
    await user.click(screen.getByRole('button', { name: '恢复默认面板布局' }))
    expect(localStorage.getItem('react-resizable-panels:trading-workspace.v1')).toBeNull()
    expect(localStorage.getItem('crypto-lab.session')).toBe('{}')
  })
})
