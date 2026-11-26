import { useEffect, useRef, useState } from 'react'
import {
  CandlestickSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
} from 'lightweight-charts'
import { rest } from '@/shared/api/client'
import { useConnectionStore, connectionDisplay } from '@/app/connectionStore'
import { useMarketStore } from './marketStore'
import { barFromPayload, candleKey, toChartData, type CandleBar } from './candles'
import { Badge, Button } from '@/shared/ui'

export const INSTRUMENT = 'okx:SPOT:BTC/USDT'
const INTERVALS = ['1m', '5m', '15m', '1h', '4h', '1d'] as const
export type CandleInterval = (typeof INTERVALS)[number]

const EMPTY_BARS: CandleBar[] = []

const QUALITY_LABEL: Record<string, string> = {
  VALID: '行情有效',
  INVALID: '行情无效',
  STALE: '行情过期',
  INCOMPLETE: '行情不完整',
  UNSYNCED: '订单簿未同步',
}

function formatTime(tsMs: number | null | undefined): string {
  if (tsMs === null || tsMs === undefined) return '—'
  return new Date(tsMs).toLocaleTimeString('zh-CN', { hour12: false })
}

/** Market Header strip + candlestick chart (docs/12 §8/§9). */
export function MarketChartPanel() {
  const [interval, setIntervalState] = useState<CandleInterval>('1m')
  const [loading, setLoading] = useState(false)
  const [hasEarlier, setHasEarlier] = useState(true)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)

  const key = candleKey(INSTRUMENT, interval)
  const bars = useMarketStore((state) => state.candles[key]) ?? EMPTY_BARS
  const ticker = useMarketStore((state) => state.tickers[INSTRUMENT])
  const quality = useMarketStore((state) => state.quality[INSTRUMENT])
  const status = useConnectionStore((state) => state.status)
  const display = connectionDisplay(status)
  const seedCandles = useMarketStore((state) => state.seedCandles)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    void rest
      .candleHistory(INSTRUMENT, interval, { limit: 200 })
      .then((result) => {
        if (cancelled) return
        seedCandles(
          INSTRUMENT,
          interval,
          result.items.map((item) => barFromPayload(item.event_id, item.payload)),
        )
        setHasEarlier(result.items.length > 0)
      })
      .catch(() => {
        if (!cancelled) setHasEarlier(false)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [interval, seedCandles])

  // Gap backfill after a resync (docs/12 §9.4).
  const resyncRef = useRef(display === 'resync')
  useEffect(() => {
    const enteredResync = display === 'resync' || display === 'offline'
    if (!enteredResync) {
      resyncRef.current = false
      return
    }
    if (resyncRef.current || display !== 'resync') return
    resyncRef.current = true
    const local = useMarketStore.getState().candles[key] ?? []
    if (local.length === 0) return
    const newest = local[local.length - 1].openTsMs
    void rest
      .candleHistory(INSTRUMENT, interval, { limit: 100, after: newest })
      .then((result) => {
        const state = useMarketStore.getState()
        const current = state.candles[candleKey(INSTRUMENT, interval)] ?? []
        const incoming = result.items.map((item) => barFromPayload(item.event_id, item.payload))
        state.seedCandles(INSTRUMENT, interval, [...current, ...incoming])
      })
      .catch(() => undefined)
  }, [display, interval, key])

  useEffect(() => {
    if (containerRef.current === null) return
    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: { background: { color: 'transparent' }, textColor: '#94a3b8' },
      grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
      timeScale: { timeVisible: true, borderColor: '#303943' },
      rightPriceScale: { borderColor: '#303943' },
    })
    const series = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderVisible: false,
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    })
    chartRef.current = chart
    seriesRef.current = series
    return () => {
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
    }
  }, [])

  useEffect(() => {
    if (seriesRef.current === null) return
    seriesRef.current.setData(toChartData(bars) as never)
  }, [bars])

  async function loadEarlier() {
    if (bars.length === 0) return
    const earliest = bars[0].openTsMs
    setLoading(true)
    try {
      const result = await rest.candleHistory(INSTRUMENT, interval, {
        limit: 200,
        before: earliest,
      })
      const page = result.items.map((item) => barFromPayload(item.event_id, item.payload))
      useMarketStore.getState().seedCandles(INSTRUMENT, interval, [...bars, ...page])
      setHasEarlier(result.items.length > 0)
    } catch {
      setHasEarlier(false)
    } finally {
      setLoading(false)
    }
  }

  const qualityOk = (quality?.status ?? 'VALID') === 'VALID'
  const marketUnavailable = !qualityOk || display === 'offline'

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-[4px] border border-line bg-surface">
      {/* Market Header (docs/12 §8) — fields without backend support show —. */}
      <div className="flex h-16 shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-b border-line px-3">
        <div>
          <span className="text-base font-semibold text-ink">BTC/USDT</span>
          <span className="ml-2 text-xs text-ink-muted">OKX · SPOT</span>
        </div>
        <span className="numeric text-2xl font-semibold text-ink">
          {ticker?.ticker.last ?? '—'}
        </span>
        <span className="numeric text-xs text-ink-secondary">
          Bid {ticker?.ticker.bid ?? '—'} / Ask {ticker?.ticker.ask ?? '—'}
        </span>
        <span className="numeric text-xs text-ink-muted">
          24H 高 {ticker?.ticker.high_24h ?? '--'} · 24H 低 {ticker?.ticker.low_24h ?? '--'} · 24H
          量 {ticker?.ticker.base_volume_24h ?? '--'}
        </span>
        <Badge tone={qualityOk ? 'positive' : 'negative'} title={quality?.reason}>
          {QUALITY_LABEL[quality?.status ?? 'VALID'] ?? quality?.status}
        </Badge>
        <span className="ml-auto text-[11px] text-ink-muted">
          来源：OKX 公共行情 · 行情时间 {formatTime(ticker?.eventTsMs)}
        </span>
      </div>

      {!qualityOk && (
        <p role="alert" className="shrink-0 bg-red-50 px-3 py-1.5 text-xs text-red-700">
          {QUALITY_LABEL[quality?.status ?? '']}：{quality?.reason ?? ''}。模拟撮合已暂停，暂不接受下单。
        </p>
      )}

      {display === 'offline' && (
        <p role="status" className="shrink-0 bg-warning/10 px-3 py-1.5 text-xs text-warning">
          连接断开，正在自动重连；行情最后更新 {formatTime(ticker?.eventTsMs)}。
        </p>
      )}

      <div className="flex h-8 shrink-0 items-center gap-1 border-b border-line px-2" role="group" aria-label="K 线周期">
        {INTERVALS.map((item) => (
          <Button
            key={item}
            variant={item === interval ? 'secondary' : 'ghost'}
            size="compact"
            onClick={() => setIntervalState(item)}
          >
            {item}
          </Button>
        ))}
        <Button
          variant="outline"
          size="compact"
          className="ml-auto"
          onClick={() => void loadEarlier()}
          disabled={loading || !hasEarlier || bars.length === 0}
        >
          {loading ? '加载中…' : '加载更早'}
        </Button>
      </div>

      <div ref={containerRef} className="min-h-0 w-full flex-1" data-testid="candle-chart" />

      {marketUnavailable && (
        <p role="status" className="shrink-0 border-t border-line px-3 py-1 text-[11px] text-ink-muted">
          行情不可用期间交易操作被禁用，恢复后自动重新可用。
        </p>
      )}
    </div>
  )
}
