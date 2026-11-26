import { beforeEach, describe, expect, test } from 'vitest'
import { useMarketStore } from './marketStore'
import type { MarketEvent } from '@/shared/api/schemas'

const TICKER_EVENT: MarketEvent = {
  protocol_version: '1.0.0',
  type: 'market.ticker',
  environment_id: 'env-1',
  stream_id: 's',
  stream_sequence: 1,
  event_id: 't-1',
  event_ts_ms: 1_100,
  published_ts_ms: 1_101,
  payload: { bid: '100.9', ask: '101.1', last: '101' },
  instrument_id: 'okx:SPOT:BTC/USDT',
}

const CANDLE_EVENT: MarketEvent = {
  protocol_version: '1.0.0',
  type: 'market.candle',
  environment_id: 'env-1',
  stream_id: 's',
  stream_sequence: 2,
  event_id: 'c-1',
  event_ts_ms: 1_200,
  published_ts_ms: 1_201,
  payload: {
    interval: '1m',
    open_ts_ms: 60_000,
    close_ts_ms: 120_000,
    open: '100',
    high: '102',
    low: '99',
    close: '101',
    is_closed: false,
  },
  instrument_id: 'okx:SPOT:BTC/USDT',
  interval: '1m',
}

beforeEach(() => {
  useMarketStore.getState().reset()
})

describe('marketStore', () => {
  test('routes ticker events per instrument', () => {
    useMarketStore.getState().applyMarketEvent(TICKER_EVENT)
    const view = useMarketStore.getState().tickers['okx:SPOT:BTC/USDT']
    expect(view?.ticker.ask).toBe('101.1')
    expect(view?.eventTsMs).toBe(1_100)
  })

  test('routes candle events into the interval bucket', () => {
    useMarketStore.getState().applyMarketEvent(CANDLE_EVENT)
    const bars = useMarketStore.getState().candles['okx:SPOT:BTC/USDT|1m']
    expect(bars).toHaveLength(1)
    expect(bars[0].close).toBe('101')
    expect(bars[0].isClosed).toBe(false)
  })

  test('routes quality events and keeps the reason', () => {
    useMarketStore.getState().applyMarketEvent({
      ...TICKER_EVENT,
      type: 'market.quality',
      event_id: 'q-1',
      payload: { quality_status: 'STALE', reason: 'market data is stale' },
    })
    const quality = useMarketStore.getState().quality['okx:SPOT:BTC/USDT']
    expect(quality?.status).toBe('STALE')
    expect(quality?.reason).toBe('market data is stale')
  })

  test('order book events update the book view', () => {
    useMarketStore.getState().applyMarketEvent({
      ...TICKER_EVENT,
      type: 'market.order_book',
      event_id: 'b-1',
      payload: {
        bids: [{ price: '100.9', quantity: '3' }],
        asks: [{ price: '101.1', quantity: '2' }],
        sequence_id: '42',
        received_ts_ms: 1_100,
      },
    })
    const book = useMarketStore.getState().orderBooks['okx:SPOT:BTC/USDT']
    expect(book?.bids).toHaveLength(1)
    expect(book?.sequenceId).toBe('42')
  })

  test('seedCandles merges REST history with live bars', () => {
    useMarketStore.getState().applyMarketEvent(CANDLE_EVENT)
    useMarketStore.getState().seedCandles('okx:SPOT:BTC/USDT', '1m', [
      {
        eventId: 'h-1',
        openTsMs: 60_000,
        closeTsMs: 120_000,
        open: '100',
        high: '100.5',
        low: '99.5',
        close: '100.2',
        baseVolume: null,
      isClosed: true,
      },
      {
        eventId: 'h-2',
        openTsMs: 0,
        closeTsMs: 60_000,
        open: '99',
        high: '100',
        low: '98',
        close: '99.5',
        baseVolume: null,
      isClosed: true,
      },
    ])
    const bars = useMarketStore.getState().candles['okx:SPOT:BTC/USDT|1m']
    expect(bars).toHaveLength(2)
    // REST history is closed and must not be reverted by the earlier
    // unclosed WS bar staying in the list ordering logic; the live bar was
    // replaced by the closed REST bar at the same open time.
    expect(bars[1].isClosed).toBe(true)
  })
})
