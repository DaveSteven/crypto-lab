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
import { Badge, Button, FinancialValue } from '@/shared/ui'

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

function chartTimeLabel(time: Time): string {
  if (typeof time === 'string') return time
  if (typeof time !== 'number') return `${time.year}-${String(time.month).padStart(2, '0')}-${String(time.day).padStart(2, '0')}`
  return new Date(time * 1_000).toLocaleString('zh-CN', {
    hour12: false,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
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
  const [fullscreen, setFullscreen] = useState(false)
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
      localization: { timeFormatter: chartTimeLabel },
      // rightOffset keeps room right of the newest bar so marker labels are not clipped by the price scale.
      timeScale: { timeVisible: true, borderColor: '#303943', rightOffset: 8, tickMarkFormatter: chartTimeLabel },
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
    <div className={fullscreen ? 'fixed inset-2 z-40 flex min-h-0 flex-col overflow-hidden rounded-[6px] border border-brand/50 bg-surface shadow-2xl' : 'flex h-full min-h-0 flex-col overflow-hidden rounded-[4px] border border-line bg-surface'}>
      {/* Market Header (docs/12 §8) — fields without backend support show —. */}
      <div className="flex min-h-[76px] shrink-0 flex-wrap items-center gap-x-5 gap-y-2 border-b border-line px-4 py-2">
        <div className="min-w-[126px]">
          <a href="/markets" className="block text-left hover:text-brand" title="切换交易对">
            <span className="block text-[17px] font-semibold text-ink">{base}/{quote}</span>
            <span className="mt-0.5 block text-[11px] text-ink-muted">{exchange.toUpperCase()} · {marketType} · 切换</span>
          </a>
        </div>
        <div className="min-w-[150px]">
          <FinancialValue className="block text-[26px] font-semibold leading-none text-ink" value={ticker?.ticker.last} kind="price" instrumentId={instrument} />
          <span className="mt-1.5 block text-[11px] text-ink-secondary">Bid <FinancialValue value={ticker?.ticker.bid} kind="price" instrumentId={instrument} /> · Ask <FinancialValue value={ticker?.ticker.ask} kind="price" instrumentId={instrument} /></span>
        </div>
        {(() => {
          const change = change24h(ticker?.ticker.last, ticker?.ticker.open_24h)
          if (change === null) return <div className="min-w-[90px]"><span className="block text-[11px] text-ink-muted">24h 涨跌</span><span className="numeric text-[14px] text-ink-muted">--</span></div>
          const up = !change.percent.startsWith('-')
          return (
            <div className="min-w-[90px]"><span className="block text-[11px] text-ink-muted">24h 涨跌</span><FinancialValue className={`text-[14px] font-medium ${up ? 'text-positive' : 'text-negative'}`} value={change.percent} kind="percent" unit="%" /></div>
          )
        })()}
        <div><span className="block text-[11px] text-ink-muted">24h 最高</span><FinancialValue className="text-[13px] text-ink-secondary" value={ticker?.ticker.high_24h} kind="price" instrumentId={instrument} /></div>
        <div><span className="block text-[11px] text-ink-muted">24h 最低</span><FinancialValue className="text-[13px] text-ink-secondary" value={ticker?.ticker.low_24h} kind="price" instrumentId={instrument} /></div>
        <div><span className="block text-[11px] text-ink-muted">24h 成交量 ({base})</span><FinancialValue className="text-[13px] text-ink-secondary" value={ticker?.ticker.base_volume_24h} kind="volume" /></div>
        <div className="ml-auto text-right">
          <Badge tone={qualityOk ? 'positive' : 'negative'} title={quality?.reason}>{QUALITY_LABEL[quality?.status ?? 'VALID'] ?? quality?.status}</Badge>
          <span className="mt-1 block text-[11px] text-ink-muted">OKX 公共行情 · {formatTime(ticker?.eventTsMs)}</span>
        </div>
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
        <Button variant="outline" size="compact" onClick={() => chartRef.current?.timeScale().scrollToRealTime()}>
          回到最新
        </Button>
        <Button variant="outline" size="compact" onClick={() => setFullscreen((value) => !value)}>
          {fullscreen ? '退出全屏' : '图表全屏'}
        </Button>
        <span className="ml-2 text-[11px] text-ink-muted">时间轴：{Intl.DateTimeFormat().resolvedOptions().timeZone}</span>
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
