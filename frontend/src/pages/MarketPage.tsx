import { useEffect, useRef, useState } from 'react'
import {
  CandlestickSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
} from 'lightweight-charts'
import { rest } from '@/api/client'
import { useConnectionStore, connectionDisplay } from '@/state/connectionStore'
import { useMarketStore } from '@/state/marketStore'
import { barFromPayload, candleKey, toChartData } from '@/market/candles'

import type { CandleBar } from '@/market/candles'

const EMPTY_BARS: CandleBar[] = []

export const INSTRUMENT = 'okx:SPOT:BTC/USDT'
const INTERVALS = ['1m', '5m', '15m', '1h', '4h', '1d'] as const
export type CandleInterval = (typeof INTERVALS)[number]

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

function formatPrice(value: string | null | undefined): string {
  return value ?? '—'
}

export function MarketPage() {
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

  // Initial history load for the selected interval.
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

  // Gap backfill: after a resync (reconnect), fetch anything newer than the
  // local newest bar so the series has no holes (docs/11 §7).
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
        const bars = result.items.map((item) => barFromPayload(item.event_id, item.payload))
        state.seedCandles(INSTRUMENT, interval, [...current, ...bars])
      })
      .catch(() => undefined)
  }, [display, interval, key])

  // Chart lifecycle.
  useEffect(() => {
    if (containerRef.current === null) return
    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: { background: { color: 'transparent' }, textColor: '#94a3b8' },
      grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
      timeScale: { timeVisible: true, borderColor: '#334155' },
      rightPriceScale: { borderColor: '#334155' },
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

  // Push merged bars into the chart incrementally on every change.
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
    <section aria-labelledby="market-title" className="space-y-4">
      <div className="flex flex-wrap items-center gap-4">
        <h1 id="market-title" className="text-lg font-semibold">
          BTC/USDT
        </h1>
        <span className="text-sm text-muted-foreground">
          Bid {formatPrice(ticker?.ticker.bid)} / Ask {formatPrice(ticker?.ticker.ask)} / Last{' '}
          {formatPrice(ticker?.ticker.last)}
        </span>
        <span
          className={
            qualityOk
              ? 'rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-800'
              : 'rounded-full bg-red-100 px-2 py-0.5 text-xs text-red-800'
          }
          title={quality?.reason}
        >
          {QUALITY_LABEL[quality?.status ?? 'VALID'] ?? quality?.status}
        </span>
        <span className="ml-auto text-xs text-muted-foreground">
          来源：OKX 公共行情 · 行情时间 {formatTime(ticker?.eventTsMs)} · 数据时间{' '}
          {formatTime(ticker?.receivedTsMs)}
        </span>
      </div>

      {!qualityOk && (
        <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          {QUALITY_LABEL[quality?.status ?? ''] }：{quality?.reason ?? '行情状态异常'}。
          模拟撮合已暂停，为保护模拟结果暂不接受下单。
        </p>
      )}
      {display === 'offline' && (
        <p role="status" className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">
          连接断开，正在自动重连；行情最后更新 {formatTime(ticker?.eventTsMs)}。
        </p>
      )}

      <div className="flex items-center gap-1" role="group" aria-label="K 线周期">
        {INTERVALS.map((item) => (
          <button
            key={item}
            type="button"
            onClick={() => setIntervalState(item)}
            className={
              item === interval
                ? 'rounded-md bg-accent px-3 py-1 text-sm font-medium'
                : 'rounded-md px-3 py-1 text-sm text-muted-foreground hover:bg-accent/50'
            }
          >
            {item}
          </button>
        ))}
        <button
          type="button"
          onClick={() => void loadEarlier()}
          disabled={loading || !hasEarlier || bars.length === 0}
          className="ml-auto rounded-md border px-3 py-1 text-sm disabled:opacity-50"
        >
          {loading ? '加载中…' : '加载更早'}
        </button>
      </div>

      <div ref={containerRef} className="h-[420px] w-full" data-testid="candle-chart" />

      {marketUnavailable && (
        <p className="text-xs text-muted-foreground">
          行情不可用期间，交易操作被禁用（模拟撮合同样暂停），恢复后自动重新可用。
        </p>
      )}
    </section>
  )
}
