import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterEach, afterAll, beforeAll, beforeEach, describe, expect, test, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { EnvironmentGate } from './EnvironmentGate'
import { useSessionStore } from '@/app/sessionStore'
import { gateway } from '@/app/gateway'

const server = setupServer()

beforeAll(() => server.listen())
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

beforeEach(() => {
  useSessionStore.getState().clearSession()
  vi.spyOn(gateway, 'start').mockImplementation(() => undefined)
  vi.spyOn(gateway, 'stop').mockImplementation(() => undefined)
})

function renderGate() {
  return render(
    <MemoryRouter>
      <EnvironmentGate>
        <div>受保护的页面内容</div>
      </EnvironmentGate>
    </MemoryRouter>,
  )
}

describe('EnvironmentGate', () => {
  test('shows the bootstrap form when no session exists', () => {
    renderGate()
    expect(screen.getByLabelText('环境名称')).toBeVisible()
    expect(screen.queryByText('受保护的页面内容')).not.toBeInTheDocument()
  })

  test('creates environment and account, then enters the session', async () => {
    const user = userEvent.setup()
    const envCalls: { key: string; body: unknown }[] = []
    server.use(
      http.get('*/api/v1/market/instruments', () =>
        HttpResponse.json({
          feed_enabled: true,
          items: ['BTC', 'ETH'].map((base) => ({
            instrument_id: `okx:SPOT:${base}/USDT`,
            exchange_id: 'okx',
            market_type: 'SPOT',
            base_asset: base,
            quote_asset: 'USDT',
          })),
        }),
      ),
      http.post('*/api/v1/environments', ({ request }) => {
        envCalls.push({
          key: request.headers.get('Idempotency-Key') ?? '',
          body: {},
        })
        return HttpResponse.json(
          {
            environment_id: 'env-new',
            name: '本地模拟环境',
            status: 'ACTIVE',
            created_ts_ms: 1_000,
            updated_ts_ms: 1_000,
          },
          { status: 201 },
        )
      }),
      http.post('*/api/v1/environments/env-new/accounts', ({ request }) => {
        expect(request.headers.get('Idempotency-Key')).toBeTruthy()
        return HttpResponse.json(
          {
            account_id: 'a-new',
            exchange_id: 'okx',
            name: 'Paper Account',
            created_ts_ms: 1_000,
            balances: [{ asset: 'USDT', available: '10000', locked: '0' }],
          },
          { status: 201 },
        )
      }),
    )
    renderGate()
    await user.click(screen.getByRole('button', { name: '创建并进入' }))
    await vi.waitFor(() => {
      expect(useSessionStore.getState().session).toEqual({
        environmentId: 'env-new',
        accountId: 'a-new',
      })
    })
    expect(envCalls[0].key).toMatch(/^[0-9a-f-]{36}$/)
    // Subscriptions follow the backend's real feed list, not the open page.
    await vi.waitFor(() =>
      expect(gateway.start).toHaveBeenCalledWith('env-new', 'a-new', [
        'okx:SPOT:BTC/USDT',
        'okx:SPOT:ETH/USDT',
      ]),
    )
    expect(screen.getByText('受保护的页面内容')).toBeInTheDocument()
  })

  test('falls back to the documented single pair only when the instrument list fails', async () => {
    server.use(http.get('*/api/v1/market/instruments', () => HttpResponse.error()))
    useSessionStore.getState().setSession({ environmentId: 'env-1', accountId: 'a-1' })
    renderGate()
    await vi.waitFor(() =>
      expect(gateway.start).toHaveBeenCalledWith('env-1', 'a-1', ['okx:SPOT:BTC/USDT']),
    )
  })

  test('reset clears the session and stops the gateway', async () => {
    useSessionStore.getState().setSession({ environmentId: 'env-1', accountId: 'a-1' })
    renderGate()
    await userEvent.click(screen.getByRole('button', { name: '重置会话' }))
    expect(useSessionStore.getState().session).toBeNull()
    expect(gateway.stop).toHaveBeenCalled()
  })
})
