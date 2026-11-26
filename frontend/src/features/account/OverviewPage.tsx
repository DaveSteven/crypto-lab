import { useEffect, useMemo, useState } from 'react'
import Decimal from 'decimal.js'
import { Link } from 'react-router-dom'
import { useMarketStore } from '@/features/market/marketStore'
import { useTradingStore } from '@/features/trading/tradingStore'
import { ExecutionsTable } from '@/features/trading/ExecutionsTable'
import { formatDecimal, formatTime } from '@/shared/lib/format'
import { Badge, EmptyState, Panel, TermTip } from '@/shared/ui'
import { computeValuation, type BidQuote } from './valuation'

function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
  return now
}

function signClass(value: string | null): string {
  if (value === null) return 'text-ink-muted'
  const n = new Decimal(value)
  return n.gt(0) ? 'text-positive' : n.lt(0) ? 'text-negative' : 'text-ink'
}

function Metric({
  label,
  value,
  tip,
  tone,
  testId,
}: {
  label: string
  value: string
  tip?: string
  tone?: string
  testId?: string
}) {
  return (
    <div className="rounded-[4px] border border-line bg-surface p-3">
      <div className="text-[11px] text-ink-muted">
        {tip ? <TermTip term={label} description={tip} /> : label}
      </div>
      <div className={`numeric mt-1 text-lg font-semibold ${tone ?? 'text-ink'}`} data-testid={testId}>
        {value}
      </div>
    </div>
  )
}

/** Overview (docs/12 §15): valuation is labelled with currency, data time and gaps; no PnL curve. */
export function OverviewPage() {
  const balances = useTradingStore((state) => state.balances)
  const positions = useTradingStore((state) => state.positions)
  const executions = useTradingStore((state) => state.executions)
  const orderBooks = useMarketStore((state) => state.orderBooks)
  const quality = useMarketStore((state) => state.quality)
  const now = useNow(1_000)

  const bids = useMemo(() => {
    const result: Record<string, BidQuote | undefined> = {}
    for (const [instrumentId, book] of Object.entries(orderBooks)) {
      const status = quality[instrumentId]?.status ?? 'VALID'
      const best = [...book.bids].sort((a, b) => new Decimal(b.price).comparedTo(a.price))[0]
      if (status === 'VALID' && best !== undefined) {
        result[instrumentId] = { price: best.price, receivedTsMs: book.receivedTsMs }
      }
    }
    return result
  }, [orderBooks, quality])

  const valuation = computeValuation({ balances, positions, executions, bids, nowMs: now })

  return (
    <div className="h-full overflow-auto p-3">
      <div className="mx-auto max-w-[1200px] space-y-3">
        <div className="flex flex-wrap items-center gap-2 text-xs text-ink-muted">
          <span>估值币种 {valuation.currency}</span>
          <span>·</span>
          <span>
            估值依据：有效买一价（Bid），不使用最新成交价 · 数据时间{' '}
            {valuation.valuationTsMs === null ? '--' : formatTime(valuation.valuationTsMs)}
          </span>
          {valuation.incomplete && (
            <Badge tone="warning" data-testid="valuation-incomplete">
              含 {valuation.unvaluable.length} 项无法估值资产，总资产不含这些资产
            </Badge>
          )}
        </div>

        <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
          <Metric
            label={valuation.incomplete ? '总资产（不完整）' : '总资产'}
            value={`${formatDecimal(valuation.totalAssets)} ${valuation.currency}`}
            testId="total-assets"
          />
          <Metric label="可用资金" value={`${formatDecimal(valuation.available)} USDT`} />
          <Metric
            label="冻结资金"
            value={`${formatDecimal(valuation.locked)} USDT`}
            tip="已被挂单或待执行订单占用、暂时不能使用的资金。"
          />
          <Metric
            label="已实现盈亏"
            tip="已卖出部分的盈亏。仅统计当前仍有记录的持仓；已完全平仓的持仓后端暂未保留，无法汇总时显示 --。"
            value={valuation.realizedPnl === null ? '--' : `${formatDecimal(valuation.realizedPnl)} USDT`}
            tone={signClass(valuation.realizedPnl)}
          />
          <Metric
            label="未实现盈亏"
            tip="按当前有效买一价估算的持仓市值减去成本；只是账面估算，未真正卖出。行情失效时显示 --。"
            value={valuation.unrealizedPnl === null ? '--' : `${formatDecimal(valuation.unrealizedPnl)} USDT`}
            tone={signClass(valuation.unrealizedPnl)}
          />
          <Metric
            label="累计手续费"
            value={
              valuation.feesByAsset.length === 0
                ? '0'
                : valuation.feesByAsset.map((f) => `${formatDecimal(f.amount)} ${f.asset}`).join(' · ')
            }
          />
        </div>

        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          <Panel title="资产分布">
            {valuation.assets.length === 0 ? (
              <EmptyState message="暂无资产。" />
            ) : (
              <ul className="space-y-2 p-3 text-xs">
                {valuation.assets
                  .filter((asset) => asset.value !== '0')
                  .map((asset) => (
                    <li key={asset.asset}>
                      <div className="numeric flex justify-between">
                        <span>{asset.asset}</span>
                        <span>
                          {formatDecimal(asset.value)} {valuation.currency} · {asset.share ?? '--'}%
                        </span>
                      </div>
                      <div className="mt-1 h-1.5 rounded bg-elevated">
                        <div
                          className="h-full rounded bg-brand"
                          style={{ width: `${asset.share ?? 0}%` }}
                        />
                      </div>
                    </li>
                  ))}
              </ul>
            )}
            {valuation.unvaluable.length > 0 && (
              <div role="status" className="border-t border-line p-3 text-xs" data-testid="unvaluable">
                <p className="mb-1 font-medium text-warning">无法估值的资产</p>
                <ul className="space-y-0.5 text-ink-secondary">
                  {valuation.unvaluable.map((asset) => (
                    <li key={asset.asset} className="numeric">
                      {asset.asset} {formatDecimal(asset.total)} — {asset.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Panel>

          <Panel title="当前持仓">
            {valuation.positions.length === 0 ? (
              <EmptyState message="暂无持仓。" />
            ) : (
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-line text-[11px] text-ink-muted">
                    <th className="py-1.5 pl-3 pr-2">品种</th>
                    <th className="py-1.5 pr-2 text-right">数量</th>
                    <th className="py-1.5 pr-2 text-right">成本</th>
                    <th className="py-1.5 pr-2 text-right">市值（Bid）</th>
                    <th className="py-1.5 pr-3 text-right">未实现盈亏</th>
                  </tr>
                </thead>
                <tbody className="numeric">
                  {valuation.positions.map((position) => (
                    <tr key={position.instrumentId} className="border-b border-line/50">
                      <td className="py-1.5 pl-3 pr-2 text-left">{position.instrumentId}</td>
                      <td className="py-1.5 pr-2">{formatDecimal(position.quantity)}</td>
                      <td className="py-1.5 pr-2">{formatDecimal(position.costBasis)}</td>
                      <td className="py-1.5 pr-2">
                        {position.marketValue === null ? '--' : formatDecimal(position.marketValue)}
                      </td>
                      <td className={`py-1.5 pr-3 ${signClass(position.unrealizedPnl)}`}>
                        {position.unrealizedPnl === null ? '--' : formatDecimal(position.unrealizedPnl)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>
        </div>

        <Panel
          title="最近模拟成交"
          actions={
            <Link to="/trading" className="text-[11px] text-brand hover:underline">
              前往交易
            </Link>
          }
        >
          <ExecutionsTable limit={5} />
        </Panel>
        <p className="text-[11px] text-ink-muted">
          以上均为模拟资产与账面估算，不代表真实收益；暂不提供收益曲线（尚无可靠历史快照）。
        </p>
      </div>
    </div>
  )
}
