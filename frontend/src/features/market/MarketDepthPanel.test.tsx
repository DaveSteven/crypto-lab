import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { MarketDepthPanel } from './MarketDepthPanel'
import { MAX_TRADES, useMarketStore } from './marketStore'
import { useOrderDraftStore } from '@/features/trading/orderDraftStore'
import { calculateVisibleDepth } from './orderBook'

const INSTRUMENT = 'okx:SPOT:BTC/USDT'
let seq = 0

function event(type: string, payload: Record<string, unknown>, eventId = `e-${(seq += 1)}`) {
  useMarketStore.getState().applyMarketEvent({
    protocol_version: '1.0.0',
    type,
    environment_id: 'env',
    stream_id: 's',
    stream_sequence: seq,
    event_id: eventId,
    event_ts_ms: 1_700_000_000_000 + seq,
    published_ts_ms: 1_700_000_000_000 + seq,
    payload,
    instrument_id: INSTRUMENT,
  } as never)
}

function book() {
  event('market.order_book', {
    bids: [{ price: '100.0', quantity: '0.5' }],
    asks: [{ price: '100.1', quantity: '0.4' }],
    sequence_id: '1',
    received_ts_ms: 1,
  })
}

beforeEach(() => {
  useMarketStore.getState().reset()
  useOrderDraftStore.setState({ pickedPrice: null, pickNonce: 0 })
})

afterEach(() => vi.unstubAllGlobals())

describe('MarketDepthPanel', () => {
  test('uses the available height for more real levels without exceeding the safety cap', () => {
    expect(calculateVisibleDepth(450)).toBe(10)
    expect(calculateVisibleDepth(720)).toBe(17)
    expect(calculateVisibleDepth(720, true)).toBe(16)
    expect(calculateVisibleDepth(10_000)).toBe(50)
  })

  test('starts observing when the first order book arrives after the empty state', async () => {
    let resize: ResizeObserverCallback | undefined
    const observe = vi.fn()
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: ResizeObserverCallback) {
        resize = callback
      }
      observe = observe
      disconnect = vi.fn()
    })
    render(<MarketDepthPanel />)
    expect(screen.getByText(/暂无订单簿数据/)).toBeVisible()

    const levels = Array.from({ length: 20 }, (_, index) => ({
      price: String(100 + index / 10),
      quantity: '0.1',
    }))
    act(() => event('market.order_book', {
      bids: levels,
      asks: levels.map((level) => ({ ...level, price: String(Number(level.price) + 10) })),
      sequence_id: 'late-book',
      received_ts_ms: 1,
    }))
    expect(await screen.findByTestId('order-book')).toBeVisible()
    expect(observe).toHaveBeenCalledOnce()

    act(() => resize?.([{ contentRect: { height: 450 } } as ResizeObserverEntry], {} as ResizeObserver))
    expect(screen.getAllByTitle('点击填入限价（不会自动下单）')).toHaveLength(20)
  })

  test('shows an honest empty state without data', () => {
    render(<MarketDepthPanel />)
    expect(screen.getByText(/暂无订单簿数据/)).toBeVisible()
  })

  test('renders levels, spread and picks a price without submitting', async () => {
    book()
    render(<MarketDepthPanel />)
    expect(screen.getByText('累计 (BTC)')).toBeVisible()
    expect(screen.getByText(/价差 0.1/)).toBeVisible()
    await userEvent.setup().click(screen.getByText('100.1'))
    expect(useOrderDraftStore.getState().pickedPrice).toBe('100.1')
  })

  test('switches order-book numbers between compact and full precision', async () => {
    event('market.order_book', {
      bids: [{ price: '100.00000000', quantity: '0.123456789' }],
      asks: [{ price: '100.10000000', quantity: '0.00000001' }],
      sequence_id: 'precision',
      received_ts_ms: 1,
    })
    const user = userEvent.setup()
    render(<MarketDepthPanel />)
    expect(screen.getAllByText('0.123457')).toHaveLength(2)
    await user.click(screen.getByRole('button', { name: /累计 \(BTC\)/ }))
    expect(screen.getAllByText('0.123456789')).toHaveLength(2)
    expect(screen.getByRole('button', { name: '完整精度' })).toHaveAttribute('aria-pressed', 'true')
  })

  test('non-VALID quality disables price picking and warns', async () => {
    book()
    event('market.quality', { quality_status: 'UNSYNCED', reason: 'gap' })
    render(<MarketDepthPanel />)
    expect(screen.getByRole('status')).toHaveTextContent('订单簿未同步')
    await userEvent.setup().click(screen.getByText('100.1'))
    expect(useOrderDraftStore.getState().pickedPrice).toBeNull()
  })

  test('market trades tab lists real trades newest first with a bounded list', async () => {
    for (let i = 0; i < MAX_TRADES + 5; i += 1) {
      event('market.trade', { trade_id: `t${i}`, price: '100', quantity: '0.1', side: i % 2 ? 'BUY' : 'SELL' })
    }
    event('market.trade', { trade_id: 't3', price: '100', quantity: '0.1', side: 'BUY' }) // duplicate
    expect(useMarketStore.getState().trades[INSTRUMENT]).toHaveLength(MAX_TRADES)
    render(<MarketDepthPanel />)
    await userEvent.setup().click(screen.getByRole('tab', { name: '最新成交' }))
    expect(screen.getByTestId('market-trades')).toBeVisible()
  })
})
