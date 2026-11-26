import { useEffect, useMemo, useRef, useState } from 'react'
import {
  CandlestickSeries,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type Time,
} from 'lightweight-charts'
import { useTradingStore } from '@/features/trading/tradingStore'
import { rest } from '@/shared/api/client'
import { gateway } from '@/app/gateway'
import { useConnectionStore, connectionDisplay } from '@/app/connectionStore'
import { useMarketStore } from './marketStore'
import {
  barFromPayload,
  buildTradeMarkers,
  candleKey,
  findGaps,
  toChartDataWithGaps,
  toVolumeData,
  type CandleBar,
} from './candles'
import { change24h } from './ticker'
import { DEFAULT_INSTRUMENT, useInstrument } from './instrumentStore'
import { Badge, Button } from '@/shared/ui'

export const INSTRUMENT = DEFAULT_INSTRUMENT
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
  const { instrumentId: instrument, exchange, marketType, base, quote } = useInstrument()
  const [interval, setIntervalState] = useState<CandleInterval>('1m')
  const [loading, setLoading] = useState(false)
  const [hasEarlier, setHasEarlier] = useState(true)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volumeRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null)
  const [legend, setLegend] = useState<CandleBar | null>(null)
  const executions = useTradingStore((state) => state.executions)

  const key = candleKey(instrument, interval)
  const bars = useMarketStore((state) => state.candles[key]) ?? EMPTY_BARS
  const ticker = useMarketStore((state) => state.tickers[instrument])
  const quality = useMarketStore((state) => state.quality[instrument])
  const status = useConnectionStore((state) => state.status)
  const display = connectionDisplay(status)
  const seedCandles = useMarketStore((state) => state.seedCandles)
  const candleError = useMarketStore((state) => state.candleSubscriptionError)

  // ADR 0008: the visible interval drives the live upstream candle channel.
  useEffect(() => {
    gateway.setCandleInterval(instrument, interval)
  }, [instrument, interval])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    void rest
      .candleHistory(instrument, interval, { limit: 200 })
      .then((result) => {
        if (cancelled) return
        seedCandles(
          instrument,
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
  }, [instrument, interval, seedCandles])

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
      .candleHistory(instrument, interval, { limit: 100, after: newest })
      .then((result) => {
        const state = useMarketStore.getState()
        const current = state.candles[candleKey(instrument, interval)] ?? []
        const incoming = result.items.map((item) => barFromPayload(item.event_id, item.payload))
        state.seedCandles(instrument, interval, [...current, ...incoming])
      })
      .catch(() => undefined)
  }, [display, instrument, interval, key])

  useEffect(() => {
    if (containerRef.current === null) return
    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: { background: { color: 'transparent' }, textColor: '#94a3b8' },
      grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
      // rightOffset keeps room right of the newest bar so marker labels are not clipped by the price scale.
      timeScale: { timeVisible: true, borderColor: '#303943', rightOffset: 8 },
      rightPriceScale: { borderColor: '#303943' },
    })
    const series = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderVisible: false,
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    })
    // Last Price Line (docs/12 §9.2) — explicit, dashed line + axis label.
    series.applyOptions({ lastValueVisible: true, priceLineVisible: true })
    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
      lastValueVisible: false,
      priceLineVisible: false,
    })
    chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } })
    series.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.22 } })
    chartRef.current = chart
    seriesRef.current = series
    volumeRef.current = volume
    markersRef.current = createSeriesMarkers(series, [])
    return () => {
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
      volumeRef.current = null
      markersRef.current = null
    }
  }, [])

  const barsRef = useRef(bars)
  useEffect(() => {
    barsRef.current = bars
  }, [bars])
  useEffect(() => {
    const chart = chartRef.current
    if (chart === null) return
    const handler = (param: { time?: Time }) => {
      if (param.time === undefined) return setLegend(null)
      const hit = barsRef.current.find((bar) => Math.floor(bar.openTsMs / 1_000) === param.time)
      setLegend(hit ?? null)
    }
    chart.subscribeCrosshairMove(handler)
    return () => chart.unsubscribeCrosshairMove(handler)
  }, [])

  useEffect(() => {
    if (seriesRef.current === null) return
    seriesRef.current.setData(toChartDataWithGaps(bars, interval) as never)
    volumeRef.current?.setData(toVolumeData(bars) as never)
  }, [bars, interval])

  const markers = useMemo(
    () => buildTradeMarkers(executions, instrument, interval),
    [executions, instrument, interval],
  )
  useEffect(() => {
    markersRef.current?.setMarkers(
      markers.map((marker) => ({
        time: marker.time as Time,
        position: marker.side === 'BUY' ? ('belowBar' as const) : ('aboveBar' as const),
        shape: marker.side === 'BUY' ? ('arrowUp' as const) : ('arrowDown' as const),
        color: marker.side === 'BUY' ? '#22c55e' : '#ef4444',
        text: marker.text,
      })),
    )
  }, [markers])

  const gaps = useMemo(() => findGaps(bars, interval), [bars, interval])
  const missingTotal = gaps.reduce((sum, gap) => sum + gap.missing, 0)
  const shown = legend ?? bars[bars.length - 1] ?? null

  async function loadEarlier() {
    if (bars.length === 0) return
    const earliest = bars[0].openTsMs
    setLoading(true)
    try {
      const result = await rest.candleHistory(instrument, interval, {
        limit: 200,
        before: earliest,
      })
      const page = result.items.map((item) => barFromPayload(item.event_id, item.payload))
      useMarketStore.getState().seedCandles(instrument, interval, [...bars, ...page])
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
          <span className="text-base font-semibold text-ink">{base}/{quote}</span>
          <span className="ml-2 text-xs text-ink-muted">{exchange.toUpperCase()} · {marketType}</span>
        </div>
        <span className="numeric text-2xl font-semibold text-ink">
          {ticker?.ticker.last ?? '—'}
        </span>
        <span className="numeric text-xs text-ink-secondary">
          Bid {ticker?.ticker.bid ?? '—'} / Ask {ticker?.ticker.ask ?? '—'}
        </span>
        {(() => {
          const change = change24h(ticker?.ticker.last, ticker?.ticker.open_24h)
          if (change === null) return <span className="numeric text-xs text-ink-muted">24H 涨跌 --</span>
          const up = !change.percent.startsWith('-')
          return (
            <span className={`numeric text-xs ${up ? 'text-positive' : 'text-negative'}`}>
              24H {up ? '+' : ''}
              {change.percent}%
            </span>
          )
        })()}
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

      <div className="relative min-h-0 w-full flex-1">
        {shown !== null && (
          <div
            className="numeric pointer-events-none absolute left-2 top-1 z-10 flex gap-3 text-[11px] text-ink-secondary"
            data-testid="ohlc-legend"
          >
            <span>开 {shown.open}</span>
            <span>高 {shown.high}</span>
            <span>低 {shown.low}</span>
            <span>收 {shown.close}</span>
            <span>量 {shown.baseVolume ?? '--'}</span>
          </div>
        )}
        <div ref={containerRef} className="h-full w-full" data-testid="candle-chart" />
      </div>

      {candleError !== null && (
        <p role="alert" className="shrink-0 border-t border-line px-3 py-1 text-[11px] text-warning">
          {interval} 周期实时订阅失败（{candleError}），仅显示历史数据。
        </p>
      )}

      {missingTotal > 0 && (
        <p role="status" className="shrink-0 border-t border-line px-3 py-1 text-[11px] text-warning">
          数据缺失：{gaps.length} 段共 {missingTotal} 根 K 线暂无数据（图中留空，未补零）。
        </p>
      )}

      {marketUnavailable && (
        <p role="status" className="shrink-0 border-t border-line px-3 py-1 text-[11px] text-ink-muted">
          行情不可用期间交易操作被禁用，恢复后自动重新可用。
        </p>
      )}
    </div>
  )
}
