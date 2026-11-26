import { useEffect, useMemo, useState } from 'react'
import Decimal from 'decimal.js'
import { Link } from 'react-router-dom'
import { useMarketStore } from '@/features/market/marketStore'
import { realizedPnlByCurrency, useTradingStore } from '@/features/trading/tradingStore'
import { ExecutionsTable } from '@/features/trading/ExecutionsTable'
import { formatTime, instrumentLabel } from '@/shared/lib/format'
import { Badge, EmptyState, FinancialValue, PageContainer, PageHeader, Panel, TermTip } from '@/shared/ui'
import { computeValuation, type BidQuote } from './valuation'

const ASSET_TONES = ['bg-brand', 'bg-info', 'bg-positive', 'bg-warning', 'bg-negative']

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
  const number = new Decimal(value)
  return number.gt(0) ? 'text-positive' : number.lt(0) ? 'text-negative' : 'text-ink-secondary'
}

function Metric({ label, value, tip, primary = false, tone, testId }: { label: string; value: React.ReactNode; tip?: string; primary?: boolean; tone?: string; testId?: string }) {
  return <div className={`rounded-[6px] border border-line bg-surface ${primary ? 'p-5' : 'p-4'}`}><div className="text-[12px] text-ink-muted">{tip ? <TermTip term={label} description={tip} /> : label}</div><div data-testid={testId} className={`${primary ? 'mt-2 text-[30px]' : 'mt-1.5 text-[20px]'} font-semibold ${tone ?? 'text-ink'}`}>{value}</div></div>
}

/** Authoritative balances/fills plus valid Bid valuation; no fabricated history. */
export function OverviewPage() {
  const balances = useTradingStore((state) => state.balances)
  const positions = useTradingStore((state) => state.positions)
  const executions = useTradingStore((state) => state.executions)
  const pnl = useTradingStore((state) => state.pnl)
  const orderBooks = useMarketStore((state) => state.orderBooks)
  const quality = useMarketStore((state) => state.quality)
  const now = useNow(1_000)
  const bids = useMemo(() => {
    const result: Record<string, BidQuote | undefined> = {}
    for (const [instrumentId, book] of Object.entries(orderBooks)) {
      const best = [...book.bids].sort((a, b) => new Decimal(b.price).comparedTo(a.price))[0]
      if ((quality[instrumentId]?.status ?? 'VALID') === 'VALID' && best !== undefined) result[instrumentId] = { price: best.price, receivedTsMs: book.receivedTsMs }
    }
    return result
  }, [orderBooks, quality])
  const valuation = computeValuation({ balances, positions, executions, bids, nowMs: now, realizedByCurrency: realizedPnlByCurrency(pnl) })
  const realizedEntries = valuation.realizedByCurrency === null ? null : Object.entries(valuation.realizedByCurrency)
  const positionValue = valuation.positions.reduce((sum, position) => sum.plus(position.marketValue ?? 0), new Decimal(0)).toString()

  return <PageContainer>
    <PageHeader title="账户总览" description={<>估值币种 USDT · 估值依据为有效买一价（Bid），不使用最新成交价 · {valuation.valuationTsMs === null ? '等待有效行情' : `更新于 ${formatTime(valuation.valuationTsMs)}`}</>} />
    {valuation.incomplete && <div className="mb-4"><Badge tone="warning" data-testid="valuation-incomplete">{valuation.unvaluable.length} 项资产暂时无法估值，总资产不包含这些资产</Badge></div>}

    <div className="grid grid-cols-4 gap-4">
      <div className="col-span-2"><Metric primary testId="total-assets" label={valuation.incomplete ? '总资产（估值不完整）' : '总资产'} value={<FinancialValue value={valuation.totalAssets} unit={valuation.currency} />} /></div>
      <Metric label="可用资金" value={<FinancialValue value={valuation.available} unit="USDT" />} />
      <Metric label="持仓市值" value={<FinancialValue value={positionValue} unit="USDT" />} />
    </div>
    <div className="mt-4 grid grid-cols-4 gap-4">
      <Metric label="冻结资金" tip="挂单或待执行订单占用的资金。" value={<FinancialValue value={valuation.locked} unit="USDT" />} />
      <Metric testId="realized-pnl" label="累计已实现盈亏" tip="由完整成交历史按移动平均成本法重建；不同币种不相加。" value={realizedEntries === null ? '—' : realizedEntries.length === 0 ? <FinancialValue value="0" unit="USDT" kind="pnl" /> : realizedEntries.map(([currency, amount], index) => <span key={currency} className={signClass(amount)}>{index > 0 && <span className="mx-1 text-ink-muted">·</span>}<FinancialValue value={amount} unit={currency} kind="pnl" /></span>)} tone={realizedEntries?.length === 1 ? signClass(realizedEntries[0][1]) : undefined} />
      <Metric label="未实现盈亏" tip="有效买一价估算的持仓市值减去成本。" value={valuation.unrealizedPnl === null ? '—' : <FinancialValue value={valuation.unrealizedPnl} unit="USDT" kind="pnl" />} tone={signClass(valuation.unrealizedPnl)} />
      <Metric label="累计手续费" value={valuation.feesByAsset.length === 0 ? <FinancialValue value="0" unit="USDT" kind="fee" /> : valuation.feesByAsset.map((fee) => <FinancialValue key={fee.asset} value={fee.amount} unit={fee.asset} kind="fee" />)} />
    </div>

    <div className="mt-5 grid grid-cols-2 gap-5">
      <Panel title="资产分布" bodyClassName="p-4">
        {valuation.assets.filter((asset) => asset.value !== '0').length === 0 ? <EmptyState message="暂无可展示资产。" /> : <><div className="flex h-3 overflow-hidden rounded-full bg-elevated" aria-label="资产估值分布">{valuation.assets.filter((asset) => asset.value !== '0').map((asset, index) => <div key={asset.asset} className={ASSET_TONES[index % ASSET_TONES.length]} style={{ width: `${asset.share ?? 0}%` }} title={`${asset.asset} ${asset.share ?? '—'}%`} />)}</div><ul className="mt-4 space-y-3 text-[13px]">{valuation.assets.filter((asset) => asset.value !== '0').map((asset, index) => <li key={asset.asset} className="flex items-center gap-3"><span className={`h-2.5 w-2.5 rounded-full ${ASSET_TONES[index % ASSET_TONES.length]}`} /><strong className="w-14 text-ink">{asset.asset}</strong><span className="ml-auto"><FinancialValue value={asset.value} unit={valuation.currency} /></span><span className="numeric w-16 text-right text-ink-muted">{asset.share ?? '—'}%</span></li>)}</ul></>}
        {valuation.unvaluable.length > 0 && <div role="status" className="mt-4 border-t border-line pt-3 text-[12px] text-warning" data-testid="unvaluable">无法估值：{valuation.unvaluable.map((asset) => `${asset.asset} ${asset.total}（${asset.reason}）`).join('、')}</div>}
      </Panel>

      <Panel title="当前持仓">
        {valuation.positions.length === 0 ? <EmptyState message="暂无持仓。完成模拟买入后，持仓会显示在这里。" /> : <table className="w-full text-[13px]"><thead><tr className="border-b border-line text-[12px] text-ink-muted"><th className="px-4 py-2.5 text-left">交易对</th><th className="py-2.5 text-right">数量</th><th className="py-2.5 text-right">平均成本</th><th className="py-2.5 text-right">总持仓成本</th><th className="px-4 py-2.5 text-right">未实现盈亏</th></tr></thead><tbody>{valuation.positions.map((position) => { const average = new Decimal(position.quantity).isZero() ? null : new Decimal(position.costBasis).div(position.quantity).toString(); return <tr key={position.instrumentId} className="border-b border-line/50"><td className="px-4 py-3 font-medium text-ink">{instrumentLabel(position.instrumentId)}</td><td className="py-3 text-right"><FinancialValue value={position.quantity} kind="quantity" instrumentId={position.instrumentId} /></td><td className="py-3 text-right"><FinancialValue value={average} kind="price" instrumentId={position.instrumentId} unit="USDT" /></td><td className="py-3 text-right"><FinancialValue value={position.costBasis} unit="USDT" /></td><td className={`px-4 py-3 text-right ${signClass(position.unrealizedPnl)}`}>{position.unrealizedPnl === null ? '—' : <FinancialValue value={position.unrealizedPnl} unit="USDT" />}</td></tr> })}</tbody></table>}
      </Panel>
    </div>
    <Panel className="mt-5" title="最近模拟成交" actions={<Link to="/trading" className="text-[13px] font-medium text-brand hover:text-brand-hover">前往交易</Link>}><ExecutionsTable limit={5} /></Panel>
    <p className="mt-3 text-[12px] text-ink-muted">以上均为模拟资产与账面估算，不代表真实收益；没有可靠历史快照，因此暂不提供收益曲线。</p>
  </PageContainer>
}
