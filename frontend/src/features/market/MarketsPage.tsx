import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import Decimal from 'decimal.js'
import { RestClient } from '@/shared/api/rest'
import { useMarketStore } from './marketStore'
import { useInstrumentStore } from './instrumentStore'
import { change24h } from './ticker'
import { useSessionStore } from '@/app/sessionStore'
import { Badge, Button, EmptyState, ErrorState, FinancialValue, Input, PageContainer, PageHeader, Panel } from '@/shared/ui'
import { cn } from '@/shared/lib/utils'

const rest = new RestClient()

const QUALITY_LABEL: Record<string, string> = {
  VALID: '有效',
  INVALID: '无效',
  STALE: '过期',
  INCOMPLETE: '不完整',
  UNSYNCED: '未同步',
}

type SortKey = 'instrument' | 'last' | 'change' | 'volume'

interface Row {
  instrumentId: string
  symbol: string
  exchange: string
  last: string | null
  change: string | null
  volume: string | null
  quality: string | null
}

function compare(a: Row, b: Row, key: SortKey, direction: 1 | -1): number {
  if (key === 'instrument') return a.symbol.localeCompare(b.symbol) * direction
  const field = key === 'last' ? 'last' : key === 'change' ? 'change' : 'volume'
  const left = a[field]
  const right = b[field]
  // Missing values always sort last in either direction, never as zero.
  if (left === null && right === null) return 0
  if (left === null) return 1
  if (right === null) return -1
  return new Decimal(left).comparedTo(right) * direction
}

/** Markets (docs/12 §16): only instruments actually connected to the feed. */
export function MarketsPage() {
  const navigate = useNavigate()
  const environmentId = useSessionStore((state) => state.session?.environmentId ?? null)
  const setInstrument = useInstrumentStore((state) => state.setInstrument)
  const tickers = useMarketStore((state) => state.tickers)
  const quality = useMarketStore((state) => state.quality)
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<{ key: SortKey; direction: 1 | -1 }>({ key: 'instrument', direction: 1 })

  // Cache is keyed by environment so switching never shows another environment's data.
  const query = useQuery({
    queryKey: ['market-instruments', environmentId],
    queryFn: () => rest.marketInstruments(),
  })

  const rows: Row[] = useMemo(
    () =>
      (query.data?.items ?? []).map((item) => {
        const ticker = tickers[item.instrument_id]?.ticker
        const change = change24h(ticker?.last, ticker?.open_24h)
        return {
          instrumentId: item.instrument_id,
          symbol: `${item.base_asset}/${item.quote_asset}`,
          exchange: item.exchange_id.toUpperCase(),
          last: ticker?.last ?? null,
          change: change?.percent ?? null,
          volume: ticker?.base_volume_24h ?? null,
          // No quality event means no state change since subscribe: with a live ticker
          // that is VALID (same default as the chart and order entry), otherwise unknown.
          quality: quality[item.instrument_id]?.status ?? (ticker !== undefined ? 'VALID' : null),
        }
      }),
    [query.data, tickers, quality],
  )

  const visible = rows
    .filter((row) => row.symbol.toLowerCase().includes(search.trim().toLowerCase()))
    .sort((a, b) => compare(a, b, sort.key, sort.direction))

  function toggleSort(key: SortKey) {
    setSort((current) =>
      current.key === key ? { key, direction: current.direction === 1 ? -1 : 1 } : { key, direction: 1 },
    )
  }

  function open(row: Row) {
    setInstrument(row.instrumentId)
    navigate('/trading')
  }

  const header = (key: SortKey, label: string, right = true) => (
    <th className={cn('py-2 pr-3', right && 'text-right')} aria-sort={sort.key === key ? (sort.direction === 1 ? 'ascending' : 'descending') : 'none'}>
      <button type="button" onClick={() => toggleSort(key)} className="hover:text-ink">
        {label}
        {sort.key === key ? (sort.direction === 1 ? ' ↑' : ' ↓') : ''}
      </button>
    </th>
  )

  return (
    <PageContainer>
      <PageHeader title="市场行情" description="仅展示当前行情 Feed 已接入的真实现货市场，不生成虚假走势。" />
      <div className="mb-5 grid grid-cols-2 gap-4">
        {rows.slice(0, 2).map((row) => (
          <div key={row.instrumentId} className="rounded-[6px] border border-line bg-surface p-5">
            <div className="flex items-start justify-between"><div><h2 className="text-[18px] font-semibold text-ink">{row.symbol}</h2><p className="mt-1 text-[12px] text-ink-muted">{row.exchange} · 现货</p></div><Badge tone={row.quality === 'VALID' ? 'positive' : 'negative'}>{row.quality === 'VALID' ? '行情有效' : '等待有效行情'}</Badge></div>
            <div className="mt-4 flex items-end justify-between"><FinancialValue className="text-[26px] font-semibold text-ink" value={row.last} kind="price" instrumentId={row.instrumentId} unit="USDT" /><div className={cn('text-[16px] font-medium', row.change === null ? 'text-ink-muted' : row.change.startsWith('-') ? 'text-negative' : 'text-positive')}>{row.change === null ? '—' : <FinancialValue value={row.change} kind="percent" unit="%" />}</div></div>
            <div className="mt-3 flex items-center justify-between text-[12px] text-ink-muted"><span>24h 成交量 <FinancialValue value={row.volume} kind="volume" unit={row.symbol.split('/')[0]} /></span><Button size="compact" variant="outline" onClick={() => open(row)}>前往交易</Button></div>
          </div>
        ))}
      </div>
        <Panel
          title="已接入市场"
          actions={
            <Input
              className="h-8 w-56 text-[13px]"
              placeholder="搜索交易对"
              aria-label="搜索交易对"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          }
        >
          {query.isError ? (
            <ErrorState message="无法获取已接入的市场列表。" onRetry={() => void query.refetch()} />
          ) : query.isPending ? (
            <EmptyState message="加载中…" />
          ) : query.data.items.length === 0 ? (
            <EmptyState message={query.data.feed_enabled ? '暂无已接入的品种。' : '行情 Feed 未启用，没有可展示的市场。'} />
          ) : (
            <table className="w-full text-left text-[13px]">
              <caption className="sr-only">已接入的现货市场</caption>
              <thead>
                <tr className="border-b border-line text-[12px] text-ink-muted">
                  {header('instrument', '交易对', false)}
                  <th className="py-2 pr-3">交易所</th>
                  {header('last', '最新价')}
                  {header('change', '24H 涨跌')}
                  {header('volume', '24H 成交量')}
                  <th className="py-2 pr-3">数据质量</th>
                </tr>
              </thead>
              <tbody className="numeric">
                {visible.map((row) => (
                  <tr
                    key={row.instrumentId}
                    className="cursor-pointer border-b border-line/50 hover:bg-elevated/40"
                    onClick={() => open(row)}
                  >
                    <td className="py-3 pl-4 pr-3 text-left">
                      <button
                        type="button"
                        className="font-medium text-brand hover:underline"
                        onClick={(event) => {
                          event.stopPropagation()
                          open(row)
                        }}
                      >
                        {row.symbol}
                      </button>
                    </td>
                    <td className="py-3 pr-3 text-left text-ink-secondary">{row.exchange} · 现货</td>
                    <td className="py-3 pr-3"><FinancialValue value={row.last} kind="price" instrumentId={row.instrumentId} unit="USDT" /></td>
                    <td
                      className={cn(
                        'py-3 pr-3',
                        row.change === null ? 'text-ink-muted' : row.change.startsWith('-') ? 'text-negative' : 'text-positive',
                      )}
                    >
                      <FinancialValue value={row.change} kind="percent" unit="%" />
                    </td>
                    <td className="py-3 pr-3"><FinancialValue value={row.volume} kind="quantity" instrumentId={row.instrumentId} unit={row.symbol.split('/')[0]} /></td>
                    <td className="py-3 pr-3 text-left">
                      <Badge tone={row.quality === 'VALID' ? 'positive' : row.quality === null ? 'neutral' : 'negative'}>
                        {row.quality === null ? '等待行情' : (QUALITY_LABEL[row.quality] ?? row.quality)}
                      </Badge>
                    </td>
                  </tr>
                ))}
                {visible.length === 0 && (
                  <tr>
                    <td colSpan={6}>
                      <EmptyState message="没有匹配的交易对。" />
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </Panel>
        <p className="mt-3 text-[12px] text-ink-muted">24h 涨跌由交易所最新价与 24h 开盘价派生；缺失值显示 —，不会当作 0。</p>
    </PageContainer>
  )
}
