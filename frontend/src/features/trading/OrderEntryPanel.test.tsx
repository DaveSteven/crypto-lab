import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, beforeAll, beforeEach, describe, expect, test } from 'vitest'
import { OrderEntryPanel } from './OrderEntryPanel'
import { useSessionStore } from '@/app/sessionStore'
import { useMarketStore } from '@/features/market/marketStore'
import { useConnectionStore } from '@/app/connectionStore'
import { useOrderDraftStore } from './orderDraftStore'
import { act } from '@testing-library/react'

const server = setupServer()

beforeAll(() => server.listen())
afterAll(() => server.close())
afterEach(() => server.resetHandlers())

beforeEach(() => {
  useSessionStore.getState().setSession({ environmentId: 'env-1', accountId: 'a-1' })
  useMarketStore.getState().reset()
  useConnectionStore.getState().update({ status: 'subscribed', resyncReason: null })
})

describe('OrderEntryPanel', () => {
  test('market buy requires the quote budget before submit', async () => {
    const user = userEvent.setup()
    render(<OrderEntryPanel />)
    await user.type(screen.getByLabelText('数量（BTC）'), '1')
    await user.click(screen.getByRole('button', { name: /提交$/ }))
    expect(screen.getByRole('alert')).toHaveTextContent('最大报价预算')
  })

  test('submits order intent with idempotency key and shows server order state', async () => {
    const user = userEvent.setup()
    let idempotencyKey = ''
    server.use(
      http.post('*/api/v1/environments/env-1/orders', ({ request }) => {
        idempotencyKey = request.headers.get('Idempotency-Key') ?? ''
        return HttpResponse.json(
          {
            order_id: 'order-abc',
            account_id: 'a-1',
            instrument_id: 'okx:SPOT:BTC/USDT',
            side: 'BUY',
            order_type: 'MARKET',
            quantity: '1',
            reference_price: '101',
            reserved_asset: 'USDT',
            reserved_amount: '105',
            filled_quantity: '0',
            cumulative_quote_amount: '0',
            cumulative_fee: '0',
            reserved_fee_rate: '0.001',
            status: 'PENDING_EXECUTION',
            submitted_ts_ms: 1_000,
            order_sequence: 1,
            created_ts_ms: 1_000,
            updated_ts_ms: 1_000,
            max_quote_budget: '105',
          },
          { status: 201 },
        )
      }),
    )
    render(<OrderEntryPanel />)
    await user.type(screen.getByLabelText('数量（BTC）'), '1')
    await user.type(screen.getByLabelText('最大报价预算（USDT，含手续费）'), '105')
    await user.click(screen.getByRole('button', { name: /提交$/ }))
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent('订单已提交')
    })
    expect(idempotencyKey).toMatch(/^[0-9a-f-]{36}$/)
  })

  test('server 503 maps to a readable error message', async () => {
    const user = userEvent.setup()
    server.use(
      http.post('*/api/v1/environments/env-1/orders', () =>
        HttpResponse.json(
          {
            error: {
              code: 'MARKET_DATA_UNAVAILABLE',
              message: 'valid order book is unavailable',
              details: {},
              request_id: 'r-1',
            },
          },
          { status: 503 },
        ),
      ),
    )
    render(<OrderEntryPanel />)
    await user.type(screen.getByLabelText('数量（BTC）'), '1')
    await user.type(screen.getByLabelText('最大报价预算（USDT，含手续费）'), '105')
    await user.click(screen.getByRole('button', { name: /提交$/ }))
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent('MARKET_DATA_UNAVAILABLE')
    })
  })

  test('non-VALID quality disables trading with the pause notice', () => {
    useMarketStore.getState().applyMarketEvent({
      protocol_version: '1.0.0',
      type: 'market.quality',
      environment_id: 'env-1',
      stream_id: 's',
      stream_sequence: 1,
      event_id: 'q-1',
      event_ts_ms: 1_000,
      published_ts_ms: 1_000,
      payload: { quality_status: 'STALE', reason: 'market data is stale' },
      instrument_id: 'okx:SPOT:BTC/USDT',
    })
    render(<OrderEntryPanel />)
    expect(screen.getByRole('alert')).toHaveTextContent('下单已暂停')
    expect(screen.getByRole('button', { name: /提交/ })).toBeDisabled()
  })

  test('a picked order-book price switches to a LIMIT draft and does not submit', async () => {
    render(<OrderEntryPanel />)
    act(() => useOrderDraftStore.getState().pickPrice('61000.5'))
    expect(await screen.findByDisplayValue('61000.5')).toBeVisible()
    expect(screen.getByRole('button', { name: '限价' })).toBeVisible()
  })
})
