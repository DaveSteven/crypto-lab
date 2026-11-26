import { describe, expect, test } from 'vitest'
import {
  barFromPayload,
  candleKey,
  mergeCandlePage,
  toChartData,
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
