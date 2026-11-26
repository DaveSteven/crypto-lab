import { memo, useEffect, useMemo, useRef, useState } from 'react'
import { useMarketStore } from './marketStore'
import { useInstrument } from './instrumentStore'
import { buildBookView, calculateVisibleDepth, type BookRow } from './orderBook'
import { useOrderDraftStore } from '@/features/trading/orderDraftStore'
import { EmptyState, Tabs } from '@/shared/ui'
import { cn } from '@/shared/lib/utils'
import { formatPercentage, formatPrice, formatQuantity, formatTime } from '@/shared/lib/format'

const TABS = [
  { value: 'book', label: '订单簿' },
  { value: 'trades', label: '最新成交' },
] as const
type DepthTab = (typeof TABS)[number]['value']

function Row({
  row,
  side,
  disabled,
  fullPrecision,
  instrumentId,
}: {
  row: BookRow
  side: 'ask' | 'bid'
  disabled: boolean
  fullPrecision: boolean
  instrumentId: string
}) {
  const pickPrice = useOrderDraftStore((state) => state.pickPrice)
  const tone = side === 'ask' ? 'text-negative bg-negative/10' : 'text-positive bg-positive/10'
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => pickPrice(row.price)}
      title={disabled ? '行情不可用，无法取价' : '点击填入限价（不会自动下单）'}
      className="relative grid h-[18px] w-full grid-cols-3 items-center gap-2 px-3 text-left text-[12px] leading-4 hover:bg-elevated disabled:cursor-not-allowed disabled:opacity-60"
    >
      <span
        aria-hidden
        className={cn('absolute inset-y-0 right-0', tone.split(' ')[1])}
        style={{ width: `${Math.round(row.depthRatio * 100)}%` }}
      />
      <span className={cn('numeric relative', tone.split(' ')[0])} title={`完整精度：${row.price}`}>{fullPrecision ? row.price : formatPrice(row.price, instrumentId)}</span>
      <span className="numeric relative text-right text-ink-secondary" title={`完整精度：${row.quantity}`}>{fullPrecision ? row.quantity : formatQuantity(row.quantity)}</span>
      <span className="numeric relative text-right text-ink-muted" title={`完整精度：${row.cumulative}`}>{fullPrecision ? row.cumulative : formatQuantity(row.cumulative)}</span>
    </button>
  )
}

const OrderBookView = memo(function OrderBookView() {
  const { instrumentId: INSTRUMENT, base, quote } = useInstrument()
  const book = useMarketStore((state) => state.orderBooks[INSTRUMENT])
  const quality = useMarketStore((state) => state.quality[INSTRUMENT])
  const hasBook = book !== undefined
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [visibleDepth, setVisibleDepth] = useState(8)
  const [fullPrecision, setFullPrecision] = useState(false)
  const qualityOk = (quality?.status ?? 'VALID') === 'VALID'
  const view = useMemo(
    () => (book ? buildBookView(book.bids, book.asks, visibleDepth) : null),
    [book, visibleDepth],
  )
  useEffect(() => {
    const node = containerRef.current
    if (node === null || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(([entry]) => {
      const rowsPerSide = calculateVisibleDepth(entry.contentRect.height, !qualityOk)
      setVisibleDepth(rowsPerSide)
    })
    observer.observe(node)
    return () => observer.disconnect()
  }, [hasBook, qualityOk])
  if (view === null || (view.asks.length === 0 && view.bids.length === 0)) {
    return <EmptyState message="暂无订单簿数据，等待行情。" />
  }
  return (
    <div ref={containerRef} className="flex min-h-0 flex-1 flex-col overflow-hidden" data-testid="order-book">
      {!qualityOk && (
        <p role="status" className="shrink-0 bg-warning/10 px-3 py-1 text-[11px] text-warning">
          订单簿{quality?.status === 'UNSYNCED' ? '未同步' : '不可用'}：{quality?.reason ?? ''}
        </p>
      )}
      <div className="grid shrink-0 grid-cols-3 gap-2 px-3 py-1.5 text-[11px] text-ink-muted">
        <span>价格 ({quote})</span>
        <span className="text-right">数量 ({base})</span>
        <button type="button" className="text-right hover:text-brand" onClick={() => setFullPrecision((value) => !value)} aria-pressed={fullPrecision} title="切换订单簿数字精度">{fullPrecision ? '完整精度' : `累计 (${base})`}</button>
      </div>
      <div className="flex min-h-0 flex-1 flex-col justify-end overflow-hidden">
        {/* Asks are drawn highest→lowest so the best ask sits next to the spread. */}
        {[...view.asks].reverse().map((row) => (
          <Row key={`a-${row.price}`} row={row} side="ask" disabled={!qualityOk} fullPrecision={fullPrecision} instrumentId={INSTRUMENT} />
        ))}
      </div>
      <div className="shrink-0 border-y border-line bg-canvas/40 px-3 py-2">
        <div className="numeric flex items-center justify-between text-[12px]">
          <span className="text-negative">卖一 {formatPrice(view.bestAsk, INSTRUMENT)}</span>
          <strong className="text-ink">价差 {formatPrice(view.spread, INSTRUMENT)}{view.spreadRate !== null && ` · ${formatPercentage(view.spreadRate, true)}%`}</strong>
          <span className="text-positive">买一 {formatPrice(view.bestBid, INSTRUMENT)}</span>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden">
        {view.bids.map((row) => (
          <Row key={`b-${row.price}`} row={row} side="bid" disabled={!qualityOk} fullPrecision={fullPrecision} instrumentId={INSTRUMENT} />
        ))}
      </div>
      <p className="shrink-0 border-t border-line px-3 py-1 text-[11px] text-ink-muted">
        真实市场深度，不代表模拟单一定能按此数量成交。
      </p>
    </div>
  )
})

const MarketTradesView = memo(function MarketTradesView() {
  const { instrumentId: INSTRUMENT } = useInstrument()
  const trades = useMarketStore((state) => state.trades[INSTRUMENT])
  if (!trades || trades.length === 0) return <EmptyState message="暂无最新成交，等待行情。" />
  return (
    <div className="min-h-0 flex-1 overflow-auto" data-testid="market-trades">
      <div className="grid grid-cols-3 px-3 py-1 text-[11px] text-ink-muted">
        <span>时间</span>
        <span className="text-right">价格</span>
        <span className="text-right">数量</span>
      </div>
      {trades.map((trade) => (
        <div key={trade.tradeId} className="grid grid-cols-3 px-3 py-[2px] text-xs">
          <span className="numeric text-ink-muted">{formatTime(trade.eventTsMs)}</span>
          <span
            className={cn('numeric text-right', trade.side === 'BUY' ? 'text-positive' : 'text-negative')}
            title={trade.side === 'BUY' ? '主动买入' : '主动卖出'}
          >
            {formatPrice(trade.price, INSTRUMENT)}
          </span>
          <span className="numeric text-right text-ink-secondary" title={`完整精度：${trade.quantity}`}>{formatQuantity(trade.quantity, INSTRUMENT)}</span>
        </div>
      ))}
      <p className="px-3 py-1 text-[10px] text-ink-muted">
        最新成交为真实市场成交；你的模拟成交见“成交记录”。
      </p>
    </div>
  )
})

/** Order Book / Market Trades tabs (docs/12 §10). Subscribes to its own store
 * slices so high-frequency updates never re-render the workspace shell. */
export function MarketDepthPanel() {
  const [tab, setTab] = useState<DepthTab>('book')
  return (
    <section
      aria-label="订单簿与最新成交"
      className="flex h-full flex-col overflow-hidden rounded-[4px] border border-line bg-surface"
    >
      <header className="flex h-9 shrink-0 items-center border-b border-line px-2">
        <Tabs items={[...TABS]} value={tab} onChange={setTab} />
      </header>
      {tab === 'book' ? <OrderBookView /> : <MarketTradesView />}
    </section>
  )
}
