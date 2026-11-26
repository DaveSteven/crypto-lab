import { formatTime, instrumentLabel } from '@/shared/lib/format'
import { useTradingStore } from './tradingStore'
import { useDetailStore } from './detailStore'
import { Button, EmptyState, FinancialValue } from '@/shared/ui'

/** Fill History view (docs/12 §12.3): read-only, server-projected. */
export function ExecutionsTable({ compact = false, limit }: { compact?: boolean; limit?: number }) {
  const executions = useTradingStore((state) => state.executions)
  const openDetail = useDetailStore((state) => state.open)
  const sorted = [...executions]
    .sort((a, b) => b.executed_ts_ms - a.executed_ts_ms)
    .slice(0, limit)

  if (sorted.length === 0) return <EmptyState message="暂无成交。" />

  return (
    <table className="w-full text-left text-xs">
      <caption className="sr-only">模拟成交记录（只读）</caption>
      <thead>
        <tr className="border-b border-line text-[11px] text-ink-muted">
          <th className="py-1.5 pl-2 pr-2">成交时间</th>
          <th className="py-1.5 pr-2">品种</th>
          <th className="py-1.5 pr-2">方向</th>
          <th className="py-1.5 pr-2 text-right">成交价</th>
          <th className="py-1.5 pr-2 text-right">数量</th>
          <th className="py-1.5 pr-2 text-right">成交额</th>
          <th className="py-1.5 pr-2 text-right">手续费</th>
          <th className="py-1.5 pr-2">订单 / 成交 ID</th>
          <th className="py-1.5 pr-2">操作</th>
        </tr>
      </thead>
      <tbody className="numeric">
        {sorted.map((execution) => (
          <tr key={execution.execution_id} className="border-b border-line/50 hover:bg-elevated/40">
            <td className="py-1.5 pl-2 pr-2 text-left">{formatTime(execution.executed_ts_ms)}</td>
            {!compact && <td className="py-1.5 pr-2 text-left">{instrumentLabel(execution.instrument_id)}</td>}
            <td className="py-1.5 pr-2 text-left">
              <span className={execution.side === 'BUY' ? 'text-positive' : 'text-negative'}>
                {execution.side === 'BUY' ? '买入' : '卖出'}
              </span>
            </td>
            <td className="py-1.5 pr-2"><FinancialValue value={execution.price} kind="price" instrumentId={execution.instrument_id} /></td>
            <td className="py-1.5 pr-2"><FinancialValue value={execution.quantity} kind="quantity" instrumentId={execution.instrument_id} /></td>
            <td className="py-1.5 pr-2"><FinancialValue value={execution.quote_amount} /></td>
            <td className="py-1.5 pr-2">
              <FinancialValue value={execution.fee_amount} kind="fee" unit={execution.fee_asset} />
            </td>
            <td className="py-1.5 pr-2 text-left text-ink-muted" title={`订单 ${execution.order_id}\n成交 ${execution.execution_id}`}>
              {execution.order_id.slice(0, 8)}… / {execution.execution_id.slice(0, 8)}…
            </td>
            <td className="py-1.5 pr-2 text-left">
              <Button variant="ghost" size="compact" onClick={() => openDetail(execution.order_id, execution.execution_id)}>
                详情
              </Button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
