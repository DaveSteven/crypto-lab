import Decimal from 'decimal.js'
import type { Candle } from '@/shared/api/schemas'

export interface CandleBar {
  eventId: string
  openTsMs: number
  closeTsMs: number
  open: string
  high: string
  low: string
  close: string
  /** null when the exchange did not provide volume (never defaulted to 0). */
  baseVolume: string | null
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
    baseVolume: candle.base_volume ?? null,
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
    const incoming = byOpenTs.get(bar.openTsMs)
    // Init race (docs/12 §9.4): a REST page that resolves after realtime
    // updates must never replace a closed bar with an unclosed snapshot, nor
    // an unclosed realtime bar with an older unclosed REST snapshot.
    if (incoming === undefined || !incoming.isClosed) {
      byOpenTs.set(bar.openTsMs, bar)
    }
  }
  const merged = [...byOpenTs.values()].sort((a, b) => a.openTsMs - b.openTsMs)
  return merged.length > maxBars ? merged.slice(merged.length - maxBars) : merged
}

export type ChartBar = { time: number; open: number; high: number; low: number; close: number }
export type VolumeBar = { time: number; value: number; color: string }
export type WhitespaceBar = { time: number }

export const INTERVAL_MS: Record<string, number> = {
  '1m': 60_000,
  '5m': 300_000,
  '15m': 900_000,
  '1h': 3_600_000,
  '4h': 14_400_000,
  '1d': 86_400_000,
}

export interface CandleGap {
  fromOpenTsMs: number
  toOpenTsMs: number
  missing: number
}

/** Missing bar ranges between consecutive bars (docs/12 §9.4: mark, never fabricate). */
export function findGaps(bars: CandleBar[], interval: string): CandleGap[] {
  const step = INTERVAL_MS[interval]
  if (step === undefined) return []
  const gaps: CandleGap[] = []
  for (let i = 1; i < bars.length; i += 1) {
    const missing = Math.round((bars[i].openTsMs - bars[i - 1].openTsMs) / step) - 1
    if (missing > 0) {
      gaps.push({
        fromOpenTsMs: bars[i - 1].openTsMs + step,
        toOpenTsMs: bars[i].openTsMs - step,
        missing,
      })
    }
  }
  return gaps
}

/** Candlestick data with blank (whitespace) slots over gaps — no zero-volume fake bars. */
export function toChartDataWithGaps(
  bars: CandleBar[],
  interval: string,
): (ChartBar | WhitespaceBar)[] {
  const step = INTERVAL_MS[interval]
  const out: (ChartBar | WhitespaceBar)[] = []
  const data = toChartData(bars)
  data.forEach((item, index) => {
    if (step !== undefined && index > 0) {
      const missing = Math.round((bars[index].openTsMs - bars[index - 1].openTsMs) / step) - 1
      // Cap whitespace fill so a very large gap cannot create unbounded points.
      for (let k = 1; k <= Math.min(missing, 500); k += 1) {
        out.push({ time: Math.floor((bars[index - 1].openTsMs + k * step) / 1_000) })
      }
    }
    out.push(item)
  })
  return out
}

/** Volume histogram; bars without exchange volume are skipped rather than drawn as 0. */
export function toVolumeData(bars: CandleBar[]): VolumeBar[] {
  const out: VolumeBar[] = []
  for (const bar of bars) {
    if (bar.baseVolume === null) continue
    out.push({
      time: Math.floor(bar.openTsMs / 1_000),
      value: Number(bar.baseVolume),
      color: Number(bar.close) >= Number(bar.open) ? '#22c55e66' : '#ef444466',
    })
  }
  return out
}

export interface FillLike {
  execution_id: string
  order_id: string
  instrument_id: string
  side: 'BUY' | 'SELL'
  price: string
  quantity: string
  executed_ts_ms: number
}

export interface TradeMarker {
  time: number
  side: 'BUY' | 'SELL'
  text: string
  executionIds: string[]
  orderIds: string[]
}

/**
 * Personal fill markers placed at the candle containing the real fill time
 * (never the order placement time). Fills of the same side in the same candle
 * are aggregated visually; executionIds keep them traceable.
 */
export function buildTradeMarkers(
  fills: FillLike[],
  instrumentId: string,
  interval: string,
): TradeMarker[] {
  const step = INTERVAL_MS[interval]
  if (step === undefined) return []
  const groups = new Map<string, FillLike[]>()
  for (const fill of fills) {
    if (fill.instrument_id !== instrumentId) continue
    const bucket = Math.floor(fill.executed_ts_ms / step) * step
    const key = `${bucket}|${fill.side}`
    groups.set(key, [...(groups.get(key) ?? []), fill])
  }
  const markers: TradeMarker[] = []
  for (const [key, group] of groups) {
    const [bucket] = key.split('|')
    const side = group[0].side
    const qty = group.reduce((sum, f) => sum.plus(f.quantity), new Decimal(0))
    markers.push({
      time: Math.floor(Number(bucket) / 1_000),
      side,
      text: `${side === 'BUY' ? '买' : '卖'} ${qty.toString()}${group.length > 1 ? ` ×${group.length}` : ''}`,
      executionIds: group.map((f) => f.execution_id),
      orderIds: [...new Set(group.map((f) => f.order_id))],
    })
  }
  return markers.sort((a, b) => a.time - b.time)
}

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
