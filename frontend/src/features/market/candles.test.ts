import { describe, expect, test } from 'vitest'
import {
  barFromPayload,
  candleKey,
  buildTradeMarkers,
  findGaps,
  mergeCandlePage,
  toChartData,
  toChartDataWithGaps,
  toVolumeData,
  upsertCandle,
  type CandleBar,
} from './candles'

function bar(openTsMs: number, close: string, isClosed = true): CandleBar {
  return {
    eventId: `e-${openTsMs}-${close}`,
    openTsMs,
    closeTsMs: openTsMs + 60_000,
    open: '100',
    high: '102',
    low: '99',
    close,
    baseVolume: '2',
    isClosed,
  }
}

describe('upsertCandle', () => {
  test('inserts new bars keeping ascending order', () => {
    let bars = upsertCandle([], bar(120_000, '101'))
    bars = upsertCandle(bars, bar(60_000, '100'))
    expect(bars.map((item) => item.openTsMs)).toEqual([60_000, 120_000])
  })

  test('unclosed updates replace the unclosed bar at the same open time', () => {
    let bars = upsertCandle([], bar(60_000, '100', false))
    bars = upsertCandle(bars, bar(60_000, '101.5', false))
    expect(bars).toHaveLength(1)
    expect(bars[0].close).toBe('101.5')
  })

  test('a closed bar is never overwritten by an unclosed update', () => {
    let bars = upsertCandle([], bar(60_000, '100.9'))
    bars = upsertCandle(bars, bar(60_000, '999', false))
    expect(bars).toHaveLength(1)
    expect(bars[0].close).toBe('100.9')
    expect(bars[0].isClosed).toBe(true)
  })

  test('a closed update replaces the unclosed bar at the same open time', () => {
    let bars = upsertCandle([], bar(60_000, '999', false))
    bars = upsertCandle(bars, bar(60_000, '100.9'))
    expect(bars[0].isClosed).toBe(true)
    expect(bars[0].close).toBe('100.9')
  })
})

describe('mergeCandlePage', () => {
  test('REST page is authoritative for its timestamps and result stays sorted', () => {
    const existing = [bar(60_000, 'wrong'), bar(180_000, 'keep')]
    const page = [bar(120_000, 'new'), bar(60_000, 'fixed')]
    const merged = mergeCandlePage(existing, page)
    expect(merged.map((item) => item.openTsMs)).toEqual([60_000, 120_000, 180_000])
    expect(merged[0].close).toBe('fixed')
  })

  test('caps the list to the newest maxBars entries', () => {
    const existing = Array.from({ length: 6 }, (_, index) => bar(index * 60_000, 'x'))
    const page = [bar(600_000, 'new')]
    const merged = mergeCandlePage(existing, page, 5)
    expect(merged).toHaveLength(5)
    expect(merged[0].openTsMs).toBe(120_000)
  })
})

describe('toChartData', () => {
  test('converts decimals to chart pixels in seconds', () => {
    const chart = toChartData([bar(60_000, '101')])
    expect(chart).toEqual([
      { time: 60, open: 100, high: 102, low: 99, close: 101 },
    ])
  })
})

describe('helpers', () => {
  test('candleKey separates instrument and interval', () => {
    expect(candleKey('okx:SPOT:BTC/USDT', '5m')).toBe('okx:SPOT:BTC/USDT|5m')
  })

  test('barFromPayload maps the canonical payload', () => {
    const result = barFromPayload(
      'evt-1',
      {
        interval: '1m',
        open_ts_ms: 60_000,
        close_ts_ms: 120_000,
        open: '100',
        high: '102',
        low: '99',
        close: '101',
        is_closed: false,
      },
    )
    expect(result).toMatchObject({ eventId: 'evt-1', openTsMs: 60_000, close: '101' })
  })
})

describe('init race protection', () => {
  test('late unclosed REST page never replaces a closed or newer realtime bar', () => {
    const existing = [bar(60_000, 'closed', true), bar(120_000, 'ws-live', false)]
    const page = [bar(60_000, 'rest-open', false), bar(120_000, 'rest-old', false)]
    const merged = mergeCandlePage(existing, page)
    expect(merged.map((b) => b.close)).toEqual(['closed', 'ws-live'])
  })

  test('closed REST bar replaces an unclosed realtime bar', () => {
    const merged = mergeCandlePage([bar(60_000, 'ws', false)], [bar(60_000, 'final', true)])
    expect(merged[0].close).toBe('final')
  })
})

describe('gaps', () => {
  test('findGaps reports missing ranges without inventing bars', () => {
    const bars = [bar(0, 'a'), bar(60_000, 'b'), bar(240_000, 'c')]
    expect(findGaps(bars, '1m')).toEqual([{ fromOpenTsMs: 120_000, toOpenTsMs: 180_000, missing: 2 }])
  })

  test('toChartDataWithGaps inserts whitespace slots only (no OHLC values)', () => {
    const data = toChartDataWithGaps([bar(0, 'a'), bar(180_000, 'b')], '1m')
    expect(data.map((d) => d.time)).toEqual([0, 60, 120, 180])
    expect('open' in data[1]).toBe(false)
  })
})

describe('volume and trade markers', () => {
  test('missing volume is skipped, not drawn as zero', () => {
    const none = { ...bar(0, '101'), baseVolume: null }
    expect(toVolumeData([none, bar(60_000, '101')])).toHaveLength(1)
  })

  test('aggregates same-side fills per candle and keeps execution traceability', () => {
    const fill = (id: string, ts: number, side: 'BUY' | 'SELL') => ({
      execution_id: id,
      order_id: 'o1',
      instrument_id: 'X',
      side,
      price: '100',
      quantity: '0.1',
      executed_ts_ms: ts,
    })
    const markers = buildTradeMarkers(
      [fill('a', 61_000, 'BUY'), fill('b', 90_000, 'BUY'), fill('c', 100_000, 'SELL')],
      'X',
      '1m',
    )
    expect(markers).toHaveLength(2)
    const buy = markers.find((m) => m.side === 'BUY')!
    expect(buy.time).toBe(60)
    expect(buy.executionIds).toEqual(['a', 'b'])
    expect(buy.text).toContain('0.2')
  })
})
