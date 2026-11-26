import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterEach, beforeAll, afterAll, describe, expect, test } from 'vitest'
import { ApiError, RestClient } from './rest'

const server = setupServer()

beforeAll(() => server.listen())
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

const ORDER = {
  order_id: 'o-1',
  account_id: 'a-1',
  instrument_id: 'okx:SPOT:BTC/USDT',
  side: 'BUY',
  order_type: 'MARKET',
  quantity: '1',
  reference_price: '101',
  reserved_asset: 'USDT',
  reserved_amount: '101.101',
  filled_quantity: '0',
  cumulative_quote_amount: '0',
  cumulative_fee: '0',
  reserved_fee_rate: '0.001',
  status: 'PENDING_EXECUTION',
  submitted_ts_ms: 1_000,
  order_sequence: 1,
  created_ts_ms: 1_000,
  updated_ts_ms: 1_000,
}

describe('RestClient', () => {
  test('createOrder sends idempotency key and validates the order contract', async () => {
    let idempotencyKey = ''
    let requestId = ''
    server.use(
      http.post('http://test/api/v1/environments/env-1/orders', ({ request }) => {
        idempotencyKey = request.headers.get('Idempotency-Key') ?? ''
        requestId = request.headers.get('X-Request-ID') ?? ''
        return HttpResponse.json(ORDER, { status: 201 })
      }),
    )
    const client = new RestClient({ baseUrl: 'http://test' })
    const order = await client.createOrder('env-1', {
      account_id: 'a-1',
      instrument_id: 'okx:SPOT:BTC/USDT',
      side: 'BUY',
      order_type: 'MARKET',
      quantity: '1',
      max_quote_budget: '105',
    })
    expect(idempotencyKey).toMatch(/^[0-9a-f-]{36}$/)
    expect(requestId).not.toBe('')
    expect(order.order_id).toBe('o-1')
    expect(order.quantity).toBe('1')
  })

  test('parses the docs/09 error envelope into ApiError', async () => {
    server.use(
      http.post('http://test/api/v1/environments/env-1/orders', () =>
        HttpResponse.json(
          {
            error: {
              code: 'MARKET_DATA_UNAVAILABLE',
              message: 'valid order book is unavailable',
              details: {},
              request_id: 'req-42',
            },
          },
          { status: 503 },
        ),
      ),
    )
    const client = new RestClient({ baseUrl: 'http://test' })
    const error = await client
      .createOrder('env-1', {
        account_id: 'a-1',
        instrument_id: 'okx:SPOT:BTC/USDT',
        side: 'BUY',
        order_type: 'MARKET',
        quantity: '1',
        max_quote_budget: '105',
      })
      .catch((reason: unknown) => reason)
    expect(error).toBeInstanceOf(ApiError)
    const apiError = error as ApiError
    expect(apiError.code).toBe('MARKET_DATA_UNAVAILABLE')
    expect(apiError.status).toBe(503)
    expect(apiError.requestId).toBe('req-42')
  })

  test('snapshot returns the validated consistency snapshot', async () => {
    server.use(
      http.get('http://test/api/v1/environments/env-1/snapshot', ({ request }) => {
        const url = new URL(request.url)
        expect(url.searchParams.get('account_id')).toBe('a-1')
        return HttpResponse.json({
          environment_id: 'env-1',
          account_id: 'a-1',
          state_version: 7,
          account: {},
          balances: [{ asset: 'USDT', available: '9898.899', locked: '0' }],
          orders: [ORDER],
          executions: [],
          positions: [],
        })
      }),
    )
    const client = new RestClient({ baseUrl: 'http://test' })
    const snapshot = await client.snapshot('env-1', 'a-1')
    expect(snapshot.state_version).toBe(7)
    expect(snapshot.balances[0].available).toBe('9898.899')
    expect(snapshot.orders[0].scheduler_lag_ms).toBeUndefined()
  })

  test('candleHistory maps pagination parameters and keeps decimals as strings', async () => {
    let query = ''
    server.use(
      http.get('http://test/api/v1/market/candles', ({ request }) => {
        query = new URL(request.url).search
        return HttpResponse.json({
          items: [
            {
              event_id: 'okx:okx:SPOT:BTC/USDT:candle:1m:60000:1',
              event_type: 'CANDLE',
              instrument_id: 'okx:SPOT:BTC/USDT',
              received_ts_ms: 1_000,
              quality_status: 'VALID',
              payload: {
                interval: '1m',
                open_ts_ms: 60_000,
                close_ts_ms: 120_000,
                open: '100',
                high: '102',
                low: '99',
                close: '101',
                is_closed: true,
              },
            },
          ],
          source: 'OKX_PUBLIC_REST',
        })
      }),
    )
    const client = new RestClient({ baseUrl: 'http://test' })
    const result = await client.candleHistory('okx:SPOT:BTC/USDT', '1m', {
      limit: 5,
      before: 120_000,
    })
    expect(query).toContain('limit=5')
    expect(query).toContain('before=120000')
    expect(result.items[0].payload.close).toBe('101')
    expect(result.items[0].payload.is_closed).toBe(true)
  })
})
