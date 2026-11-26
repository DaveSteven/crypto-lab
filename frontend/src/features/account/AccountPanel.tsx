import { formatDecimal } from '@/shared/lib/format'
import { useTradingStore } from '@/features/trading/tradingStore'
import { EmptyState, TermTip } from '@/shared/ui'

/** Balances / Positions views (docs/12 §12.4/§12.5). */
export function AccountPanel({ view }: { view: 'balances' | 'positions' }) {
  const balances = useTradingStore((state) => state.balances)
  const positions = useTradingStore((state) => state.positions)

  if (view === 'balances') {
    if (balances.length === 0) return <EmptyState message="暂无余额记录。" />
    return (
      <table className="w-full text-left text-xs">
        <caption className="sr-only">资产余额（Ledger 权威投影）</caption>
        <thead>
          <tr className="border-b border-line text-[11px] text-ink-muted">
            <th className="py-1.5 pl-2 pr-2">资产</th>
            <th className="py-1.5 pr-2 text-right">可用</th>
            <th className="py-1.5 pr-2 text-right">冻结</th>
          </tr>
        </thead>
        <tbody className="numeric">
          {balances.map((balance) => (
            <tr key={balance.asset} className="border-b border-line/50 hover:bg-elevated/40">
              <td className="py-1.5 pl-2 pr-2 text-left">{balance.asset}</td>
              <td className="py-1.5 pr-2">{formatDecimal(balance.available)}</td>
              <td className="py-1.5 pr-2">{formatDecimal(balance.locked)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    )
  }

  if (positions.length === 0) return <EmptyState message="暂无持仓。" />
  return (
    <table className="w-full text-left text-xs">
      <caption className="sr-only">持仓投影（移动平均成本法）</caption>
      <thead>
        <tr className="border-b border-line text-[11px] text-ink-muted">
          <th className="py-1.5 pl-2 pr-2">品种</th>
          <th className="py-1.5 pr-2 text-right">数量</th>
          <th className="py-1.5 pr-2 text-right">
            <TermTip term="平均成本" description="移动平均成本法：买入手续费计入持仓成本。" />
          </th>
          <th className="py-1.5 pr-2 text-right">成本基础</th>
          <th className="py-1.5 pr-2 text-right">
            <TermTip term="已实现盈亏" description="卖出金额减手续费与对应持仓成本；仅在平仓时产生。" />
          </th>
          <th className="py-1.5 pr-2 text-right">累计手续费</th>
        </tr>
      </thead>
      <tbody className="numeric">
        {positions.map((position) => (
          <tr key={position.instrument_id} className="border-b border-line/50 hover:bg-elevated/40">
            <td className="py-1.5 pl-2 pr-2 text-left">{position.instrument_id}</td>
            <td className="py-1.5 pr-2">{formatDecimal(position.quantity)}</td>
            <td className="py-1.5 pr-2">{formatDecimal(position.average_cost)}</td>
            <td className="py-1.5 pr-2">{formatDecimal(position.cost_basis)}</td>
            <td className="py-1.5 pr-2">{formatDecimal(position.realized_pnl)}</td>
            <td className="py-1.5 pr-2">{formatDecimal(position.cumulative_fees)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
