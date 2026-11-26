import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, beforeAll, beforeEach, describe, expect, test, vi } from 'vitest'
import { OrdersTable } from './OrdersTable'
import { useSessionStore } from '@/app/sessionStore'
import { useTradingStore } from '@/features/trading/tradingStore'
import type { Snapshot } from '@/shared/api/schemas'
import { gateway } from '@/app/gateway'

const server = setupServer()

beforeAll(() => server.listen())
afterAll(() => server.close())

const SNAPSHOT: Snapshot = {
  environment_id: 'env-1',
  account_id: 'a-1',
  state_version: 3,
  account: {},
  balances: [],
  orders: [
    {
      order_id: 'order-open',
      account_id: 'a-1',
      instrument_id: 'okx:SPOT:BTC/USDT',
      side: 'BUY',
      order_type: 'LIMIT',
      quantity: '1',
      reference_price: '100',
      reserved_asset: 'USDT',
      reserved_amount: '101',
      filled_quantity: '0',
      cumulative_quote_amount: '0',
      cumulative_fee: '0',
      reserved_fee_rate: '0.001',
      time_in_force: 'GTC',
      status: 'OPEN',
      submitted_ts_ms: 1_000,
      configured_latency_ms: 500,
      actual_simulated_delay_ms: 600,
      scheduler_lag_ms: 100,
      order_sequence: 1,
      created_ts_ms: 1_000,
      updated_ts_ms: 1_100,
    },
  ],
  executions: [],
  positions: [],
}

beforeEach(() => {
  useSessionStore.getState().setSession({ environmentId: 'env-1', accountId: 'a-1' })
  useTradingStore.getState().applySnapshot(SNAPSHOT)
  vi.spyOn(gateway, 'resyncNow').mockResolvedValue(undefined)
})

describe('OrdersTable', () => {
  test('renders orders with latency and scheduler lag columns', () => {
    render(<OrdersTable filter="history" emptyMessage="暂无" />)
    expect(screen.getByText('500 ms')).toBeVisible()
    expect(screen.getByText('600 ms')).toBeVisible()
    expect(screen.getByText('100 ms')).toBeVisible()
    expect(screen.getByText('OPEN')).toBeVisible()
    expect(screen.getByRole('button', { name: '取消' })).toBeEnabled()
  })

  test('cancel posts with an idempotency key and refreshes via resync', async () => {
    const user = userEvent.setup()
    let idempotencyKey = ''
    server.use(
      http.post('*/api/v1/environments/env-1/orders/order-open/cancel', ({ request }) => {
        idempotencyKey = request.headers.get('Idempotency-Key') ?? ''
        return HttpResponse.json(
          {
            ...SNAPSHOT.orders[0],
            status: 'CANCELED',
            termination_reason: 'CLIENT_REQUEST',
          },
          { status: 200 },
        )
      }),
    )
    render(<OrdersTable filter="history" emptyMessage="暂无" />)
    await user.click(screen.getByRole('button', { name: '取消' }))
    await waitFor(() => {
      expect(idempotencyKey).toMatch(/^[0-9a-f-]{36}$/)
      expect(gateway.resyncNow).toHaveBeenCalled()
    })
  })

  test('domain conflict on cancel shows the error code', async () => {
    const user = userEvent.setup()
    server.use(
      http.post('*/api/v1/environments/env-1/orders/order-open/cancel', () =>
        HttpResponse.json(
          {
            error: {
              code: 'INVALID_ORDER_STATE',
              message: 'order is already filled',
              details: {},
              request_id: 'r-2',
            },
          },
          { status: 409 },
        ),
      ),
    )
    render(<OrdersTable filter="history" emptyMessage="暂无" />)
    await user.click(screen.getByRole('button', { name: '取消' }))
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('INVALID_ORDER_STATE')
    })
  })
})
