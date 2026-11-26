import { QueryClient } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, test, vi } from 'vitest'
import { switchEnvironment } from './environmentSwitch'
import { gateway } from '@/app/gateway'
import { useSessionStore } from '@/app/sessionStore'
import { useMarketStore } from '@/features/market/marketStore'
import { useTradingStore } from '@/features/trading/tradingStore'
import type { Snapshot } from '@/shared/api/schemas'

const server = setupServer()
beforeAll(() => server.listen())
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

beforeEach(() => {
  vi.spyOn(gateway, 'stop').mockImplementation(() => undefined)
  useSessionStore.getState().setSession({ environmentId: 'env-old', accountId: 'a-old' })
  useTradingStore.getState().applySnapshot({
    environment_id: 'env-old',
    account_id: 'a-old',
    state_version: 9,
    account: {},
    balances: [{ asset: 'USDT', available: '123', locked: '0' }],
    orders: [{ order_id: 'old-order' } as never],
    executions: [],
    positions: [],
  } as unknown as Snapshot)
  useMarketStore.getState().setCandleSubscriptionError('x')
})

describe('switchEnvironment', () => {
  test('drops old subscription, state and cache before entering the new environment', async () => {
    server.use(
      http.get('*/api/v1/environments/env-new/accounts', () =>
        HttpResponse.json({
          items: [{ account_id: 'a-new', exchange_id: 'okx', name: 'N', created_ts_ms: 1 }],
        }),
      ),
    )
    const queryClient = new QueryClient()
    queryClient.setQueryData(['accounts', 'env-old'], ['stale'])
    await switchEnvironment('env-new', queryClient)

    expect(gateway.stop).toHaveBeenCalled()
    const trading = useTradingStore.getState()
    expect(trading.orders).toEqual([])
    expect(trading.balances).toEqual([])
    expect(trading.synced).toBe(false) // trading disabled until the new snapshot arrives
    expect(useMarketStore.getState().candleSubscriptionError).toBeNull()
    expect(queryClient.getQueryData(['accounts', 'env-old'])).toBeUndefined()
    expect(useSessionStore.getState().session).toEqual({ environmentId: 'env-new', accountId: 'a-new' })
  })

  test('an environment without an account is refused and nothing is torn down', async () => {
    server.use(http.get('*/api/v1/environments/env-empty/accounts', () => HttpResponse.json({ items: [] })))
    await expect(switchEnvironment('env-empty', new QueryClient())).rejects.toThrow('没有模拟账户')
    expect(useSessionStore.getState().session?.environmentId).toBe('env-old')
    expect(useTradingStore.getState().orders).toHaveLength(1)
  })

  test('switching to the current environment is a no-op', async () => {
    await switchEnvironment('env-old', new QueryClient())
    expect(gateway.stop).not.toHaveBeenCalled()
  })
})
