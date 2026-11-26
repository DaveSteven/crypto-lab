import type { Candle } from '@/api/schemas'

export interface CandleBar {
  eventId: string
  openTsMs: number
  closeTsMs: number
  open: string
  high: string
  low: string
  close: string
  isClosed: boolean
}

export function candleKey(instrumentId: string, interval: string): string {
  return `${instrumentId}|${interval}`
}

export function barFromPayload(eventId: string, candle: Candle): CandleBar {
  return {
    eventId,
    openTsMs: candle.open_ts_ms,
    closeTsMs: candle.close_ts_ms,
    open: candle.open,
    high: candle.high,
    low: candle.low,
    close: candle.close,
    isClosed: candle.is_closed,
  }
}

/**
 * Insert one realtime candle update into a sorted bar list.
 *
 * - An update for an already closed bar never overwrites it (closed K 线保护).
 * - Unclosed updates replace the unclosed bar with the same open time.
 * - The list stays sorted by open time ascending.
 */
export function upsertCandle(bars: CandleBar[], incoming: CandleBar): CandleBar[] {
  const index = bars.findIndex((bar) => bar.openTsMs === incoming.openTsMs)
  if (index === -1) {
    const next = [...bars, incoming]
    next.sort((a, b) => a.openTsMs - b.openTsMs)
    return next
  }
  const existing = bars[index]
  if (existing.isClosed && !incoming.isClosed) {
    return bars
  }
  const next = bars.slice()
  next[index] = incoming
  return next
}

/**
 * Merge a REST history page into the local list. REST is authoritative for
 * the timestamps it returns (history/pagination/backfill all flow through
 * here), so those bars are replaced outright.
 */
export function mergeCandlePage(
  existing: CandleBar[],
  page: CandleBar[],
  maxBars = 5_000,
): CandleBar[] {
  const byOpenTs = new Map<number, CandleBar>()
  for (const bar of page) byOpenTs.set(bar.openTsMs, bar)
  for (const bar of existing) {
    if (!byOpenTs.has(bar.openTsMs)) byOpenTs.set(bar.openTsMs, bar)
  }
  const merged = [...byOpenTs.values()].sort((a, b) => a.openTsMs - b.openTsMs)
  return merged.length > maxBars ? merged.slice(merged.length - maxBars) : merged
}

export type ChartBar = { time: number; open: number; high: number; low: number; close: number }

/**
 * Chart pixels only — the display layer may convert to float, per
 * docs/11 §5; every monetary value shown as text still uses decimals.
 */
export function toChartData(bars: CandleBar[]): ChartBar[] {
  return bars.map((bar) => ({
    time: Math.floor(bar.openTsMs / 1_000),
    open: Number(bar.open),
    high: Number(bar.high),
    low: Number(bar.low),
    close: Number(bar.close),
  }))
}
