import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, beforeAll, beforeEach, describe, expect, test } from 'vitest'
import { OrderEntryPanel } from './OrderEntryPanel'
import { useSessionStore } from '@/app/sessionStore'
import { useMarketStore } from '@/features/market/marketStore'
import { useConnectionStore } from '@/app/connectionStore'
import { useInstrumentStore } from '@/features/market/instrumentStore'
import { useOrderDraftStore } from './orderDraftStore'
import { useTradingStore } from './tradingStore'
import { act } from '@testing-library/react'

const server = setupServer()

beforeAll(() => server.listen())
afterAll(() => server.close())
afterEach(() => server.resetHandlers())

beforeEach(() => {
  useSessionStore.getState().setSession({ environmentId: 'env-1', accountId: 'a-1' })
  useMarketStore.getState().reset()
  useTradingStore.getState().reset()
  useTradingStore.setState({ synced: true }) // authoritative snapshot applied
  useConnectionStore.getState().update({ status: 'subscribed', resyncReason: null })
  useInstrumentStore.getState().setInstrument('okx:SPOT:BTC/USDT')
})

describe('OrderEntryPanel', () => {
  test('market buy preview stays disabled until the required budget is valid', async () => {
    const user = userEvent.setup()
    render(<OrderEntryPanel />)
    const preview = screen.getByRole('button', { name: '预览买入订单' })
    expect(preview).toBeDisabled()
    await user.type(screen.getByLabelText('数量（BTC）'), '1')
    expect(preview).toBeDisabled()
    await user.type(screen.getByLabelText('最大报价预算（USDT，含手续费）'), '105')
    expect(preview).toBeEnabled()
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
    await user.click(screen.getByRole('button', { name: '预览买入订单' }))
    await user.click(screen.getByRole('button', { name: '确认提交' }))
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
    await user.click(screen.getByRole('button', { name: '预览买入订单' }))
    await user.click(screen.getByRole('button', { name: '确认提交' }))
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
    expect(screen.getByRole('button', { name: '预览买入订单' })).toBeDisabled()
  })

  test('a picked order-book price switches to a LIMIT draft and does not submit', async () => {
    render(<OrderEntryPanel />)
    act(() => useOrderDraftStore.getState().pickPrice('61000.5'))
    expect(await screen.findByDisplayValue('61000.5')).toBeVisible()
    expect(screen.getByRole('button', { name: '限价' })).toBeVisible()
  })

  test('confirmation dialog previews the order and nothing is sent until confirmed', async () => {
    const user = userEvent.setup()
    let calls = 0
    server.use(
      http.post('*/api/v1/environments/env-1/orders', () => {
        calls += 1
        return HttpResponse.json({}, { status: 500 })
      }),
    )
    render(<OrderEntryPanel />)
    await user.type(screen.getByLabelText('数量（BTC）'), '1')
    await user.type(screen.getByLabelText('最大报价预算（USDT，含手续费）'), '105')
    await user.click(screen.getByRole('button', { name: '预览买入订单' }))
    const dialog = screen.getByRole('dialog', { name: '确认下单' })
    expect(dialog).toHaveTextContent('本地参考估算')
    expect(dialog).toHaveTextContent('行情缺失')
    expect(calls).toBe(0)
    await user.click(screen.getByRole('button', { name: '返回修改' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(calls).toBe(0)
  })

  test('Escape closes the confirmation without submitting', async () => {
    const user = userEvent.setup()
    render(<OrderEntryPanel />)
    await user.type(screen.getByLabelText('数量（BTC）'), '1')
    await user.type(screen.getByLabelText('最大报价预算（USDT，含手续费）'), '105')
    await user.click(screen.getByRole('button', { name: '预览买入订单' }))
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  test('shows the available balance and fills quantity from a percentage', async () => {
    const user = userEvent.setup()
    useTradingStore.setState({ balances: [{ asset: 'BTC', available: '2', locked: '0' }] })
    render(<OrderEntryPanel />)
    await user.click(screen.getByRole('button', { name: '卖出' }))
    expect(screen.getByTestId('available-balance')).toHaveTextContent(/2\s*BTC/)
    await user.click(screen.getByRole('button', { name: '50%' }))
    expect(screen.getByLabelText('数量（BTC）')).toHaveValue('1')
  })

  test('orders target the selected instrument and use its own asset labels', async () => {
    const user = userEvent.setup()
    useInstrumentStore.getState().setInstrument('okx:SPOT:ETH/USDT')
    useTradingStore.setState({ balances: [{ asset: 'ETH', available: '3', locked: '0' }] })
    let body: Record<string, unknown> = {}
    server.use(
      http.post('*/api/v1/environments/env-1/orders', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ error: { code: 'X', message: 'stop', details: {}, request_id: 'r' } }, { status: 400 })
      }),
    )
    render(<OrderEntryPanel />)
    await user.click(screen.getByRole('button', { name: '卖出' }))
    expect(screen.getByTestId('available-balance')).toHaveTextContent(/3\s*ETH/)
    await user.type(screen.getByLabelText('数量（ETH）'), '1')
    await user.click(screen.getByRole('button', { name: '预览卖出订单' }))
    expect(screen.getByRole('dialog')).toHaveTextContent('ETH/USDT')
    await user.click(screen.getByRole('button', { name: '确认提交' }))
    await waitFor(() => expect(body.instrument_id).toBe('okx:SPOT:ETH/USDT'))
    useInstrumentStore.getState().setInstrument('okx:SPOT:BTC/USDT')
  })

  test('trading stays disabled until the account snapshot is applied (e.g. after an environment switch)', async () => {
    useTradingStore.getState().reset() // synced: false
    render(<OrderEntryPanel />)
    expect(screen.getByRole('alert')).toHaveTextContent('账户状态同步中')
    expect(screen.getByRole('button', { name: '预览买入订单' })).toBeDisabled()
  })

  test('quote amount mode derives a Decimal quantity and keeps the budget explicit', async () => {
    const user = userEvent.setup()
    useMarketStore.getState().applyMarketEvent({
      protocol_version: '1.0.0',
      type: 'market.ticker',
      environment_id: 'env-1',
      stream_id: 's',
      stream_sequence: 1,
      event_id: 'ticker-1',
      event_ts_ms: 1_000,
      published_ts_ms: 1_000,
      payload: { bid: '99', ask: '100', last: '100' },
      instrument_id: 'okx:SPOT:BTC/USDT',
    })
    render(<OrderEntryPanel />)
    await user.click(screen.getByRole('button', { name: '按 USDT 金额' }))
    await user.type(screen.getByRole('textbox', { name: /最大资金预算/ }), '100.1')
    expect(screen.getByText(/按参考 Ask 换算数量/)).toHaveTextContent('1 BTC')
  })
})
