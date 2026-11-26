import { useState } from 'react'
import { ApiError } from '@/shared/api/rest'
import { rest } from '@/shared/api/client'
import { formatDecimal, formatTime } from '@/shared/lib/format'
import { gateway } from '@/app/gateway'
import { useSessionStore } from '@/app/sessionStore'
import { useTradingStore } from './tradingStore'
import { useDetailStore } from './detailStore'
import { OPEN_STATUSES, fillSummary, remainingQuantity, statusLabel } from './orderStatus'
import { Button, EmptyState } from '@/shared/ui'


/** Orders table used inside the Account Activity Panel (docs/12 §12.1/§12.2). */
export function OrdersTable({
  filter,
  emptyMessage,
}: {
  filter: 'open' | 'history'
  emptyMessage: string
}) {
  const session = useSessionStore((state) => state.session)
  const orders = useTradingStore((state) => state.orders)
  const [cancelError, setCancelError] = useState<string | null>(null)
  const [cancelingId, setCancelingId] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const openDetail = useDetailStore((state) => state.open)

  const sorted = [...orders].sort((a, b) => b.order_sequence - a.order_sequence)
  const visible =
    filter === 'open'
      ? sorted.filter((order) => OPEN_STATUSES.has(order.status))
      : sorted

  async function handleCancel(orderId: string) {
    if (session === null || cancelingId !== null) return
    setCancelingId(orderId)
    setCancelError(null)
    try {
      await rest.cancelOrder(session.environmentId, orderId)
      await gateway.resyncNow()
    } catch (reason) {
      if (reason instanceof ApiError) {
        setCancelError(`取消失败（${reason.code}）：${reason.message}`)
      } else {
        setCancelError(`取消失败：${reason instanceof Error ? reason.message : String(reason)}`)
      }
    } finally {
      setCancelingId(null)
    }
  }

  async function handleRefresh() {
    setRefreshing(true)
    try {
      await gateway.resyncNow()
    } finally {
      setRefreshing(false)
    }
  }

  if (visible.length === 0) return <EmptyState message={emptyMessage} />

  return (
    <div className="space-y-1">
      {filter === 'history' && (
        <div className="px-2 pt-1">
          <Button variant="outline" size="compact" onClick={() => void handleRefresh()} disabled={refreshing}>
            {refreshing ? '刷新中…' : '从服务端刷新'}
          </Button>
        </div>
      )}
      {cancelError !== null && (
        <p role="alert" className="px-2 text-xs text-negative">
          {cancelError}
        </p>
      )}
      <table className="w-full text-left text-xs">
        <caption className="sr-only">模拟订单</caption>
        <thead>
          <tr className="border-b border-line text-[11px] text-ink-muted">
            <th className="py-1.5 pl-2 pr-2">时间</th>
            <th className="py-1.5 pr-2">方向</th>
            <th className="py-1.5 pr-2">类型</th>
            <th className="py-1.5 pr-2 text-right">限价</th>
            <th className="py-1.5 pr-2">状态</th>
            <th className="py-1.5 pr-2 text-right">数量/已成交</th>
            <th className="py-1.5 pr-2 text-right">剩余</th>
            <th className="py-1.5 pr-2 text-right">均价</th>
            <th className="py-1.5 pr-2 text-right">手续费</th>
            <th className="py-1.5 pr-2 text-right">配置延迟</th>
            <th className="py-1.5 pr-2 text-right">实际延迟</th>
            <th className="py-1.5 pr-2 text-right">调度滞后</th>
            <th className="py-1.5 pr-2">操作</th>
          </tr>
        </thead>
        <tbody className="numeric">
          {visible.map((order) => (
            <tr key={order.order_id} className="border-b border-line/50 hover:bg-elevated/40">
              <td className="py-1.5 pl-2 pr-2 text-left">{formatTime(order.submitted_ts_ms)}</td>
              <td className="py-1.5 pr-2 text-left">
                <span className={order.side === 'BUY' ? 'text-positive' : 'text-negative'}>
                  {order.side === 'BUY' ? '买入' : '卖出'}
                </span>
              </td>
              <td className="py-1.5 pr-2 text-left">{order.order_type === 'MARKET' ? '市价' : '限价'}</td>
              <td className="py-1.5 pr-2">{formatDecimal(order.limit_price)}</td>
              <td className="py-1.5 pr-2 text-left">
                <div>{statusLabel(order.status)}</div>
                {fillSummary(order) !== null && (
                  <div className="text-[10px] text-ink-muted">{fillSummary(order)}</div>
                )}
              </td>
              <td className="py-1.5 pr-2">
                {formatDecimal(order.quantity)} / {formatDecimal(order.filled_quantity)}
              </td>
              <td className="py-1.5 pr-2">{remainingQuantity(order)}</td>
              <td className="py-1.5 pr-2">{formatDecimal(order.average_fill_price)}</td>
              <td className="py-1.5 pr-2">{formatDecimal(order.cumulative_fee)}</td>
              <td className="py-1.5 pr-2">{order.configured_latency_ms ?? '—'} ms</td>
              <td className="py-1.5 pr-2" title="实际执行 − 提交时间">
                {order.actual_simulated_delay_ms ?? '—'} ms
              </td>
              <td className="py-1.5 pr-2" title="实际执行 − 计划执行（模拟调度粒度）">
                {order.scheduler_lag_ms ?? '—'} ms
              </td>
              <td className="flex gap-1 py-1.5 pr-2 text-left">
                <Button variant="ghost" size="compact" onClick={() => openDetail(order.order_id)}>
                  详情
                </Button>
                {OPEN_STATUSES.has(order.status) ? (
                  <Button
                    variant="outline"
                    size="compact"
                    onClick={() => void handleCancel(order.order_id)}
                    disabled={cancelingId === order.order_id}
                  >
                    {cancelingId === order.order_id ? '取消中…' : '取消'}
                  </Button>
                ) : (
                  <span className="text-ink-muted">{order.termination_reason ?? '—'}</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
