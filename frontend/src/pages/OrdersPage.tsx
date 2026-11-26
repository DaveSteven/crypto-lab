import { useState } from 'react'
import { ApiError } from '@/api/rest'
import { rest } from '@/api/client'
import { formatDecimal, formatTime } from '@/lib/format'
import { gateway } from '@/realtime/gateway'
import { useSessionStore } from '@/state/sessionStore'
import { useTradingStore } from '@/state/tradingStore'

const OPEN_STATUSES = new Set(['PENDING_EXECUTION', 'OPEN', 'PARTIALLY_FILLED'])

export function OrdersPage() {
  const session = useSessionStore((state) => state.session)
  const orders = useTradingStore((state) => state.orders)
  const [cancelError, setCancelError] = useState<string | null>(null)
  const [cancelingId, setCancelingId] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  const sorted = [...orders].sort(
    (a, b) => b.order_sequence - a.order_sequence,
  )

  async function handleCancel(orderId: string) {
    if (session === null || cancelingId !== null) return
    setCancelingId(orderId)
    setCancelError(null)
    try {
      await rest.cancelOrder(session.environmentId, orderId)
      // The committed orders topic event updates the store; resync guarantees it.
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

  return (
    <section aria-labelledby="orders-title" className="space-y-3">
      <div className="flex items-center gap-3">
        <h1 id="orders-title" className="text-lg font-semibold">
          订单
        </h1>
        <button
          type="button"
          onClick={() => void handleRefresh()}
          disabled={refreshing}
          className="rounded-md border px-3 py-1 text-sm disabled:opacity-50"
        >
          {refreshing ? '刷新中…' : '从服务端刷新'}
        </button>
      </div>
      {cancelError !== null && (
        <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          {cancelError}
        </p>
      )}
      {sorted.length === 0 ? (
        <p className="text-sm text-muted-foreground">暂无订单。</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">模拟订单列表</caption>
            <thead>
              <tr className="border-b text-xs text-muted-foreground">
                <th className="py-2 pr-3">时间</th>
                <th className="py-2 pr-3">方向</th>
                <th className="py-2 pr-3">类型</th>
                <th className="py-2 pr-3">状态</th>
                <th className="py-2 pr-3">数量/已成交</th>
                <th className="py-2 pr-3">均价</th>
                <th className="py-2 pr-3">手续费</th>
                <th className="py-2 pr-3">配置延迟</th>
                <th className="py-2 pr-3">实际模拟延迟</th>
                <th className="py-2 pr-3">调度滞后</th>
                <th className="py-2 pr-3">操作</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((order) => (
                <tr key={order.order_id} className="border-b">
                  <td className="py-2 pr-3">{formatTime(order.submitted_ts_ms)}</td>
                  <td className="py-2 pr-3">{order.side === 'BUY' ? '买入' : '卖出'}</td>
                  <td className="py-2 pr-3">{order.order_type === 'MARKET' ? '市价' : '限价'}</td>
                  <td className="py-2 pr-3">{order.status}</td>
                  <td className="py-2 pr-3">
                    {formatDecimal(order.quantity)} / {formatDecimal(order.filled_quantity)}
                  </td>
                  <td className="py-2 pr-3">{formatDecimal(order.average_fill_price)}</td>
                  <td className="py-2 pr-3">{formatDecimal(order.cumulative_fee)}</td>
                  <td className="py-2 pr-3">{order.configured_latency_ms ?? '—'} ms</td>
                  <td className="py-2 pr-3">{order.actual_simulated_delay_ms ?? '—'} ms</td>
                  <td className="py-2 pr-3" title="实际执行时间 − 计划执行时间（模拟调度粒度）">
                    {order.scheduler_lag_ms ?? '—'} ms
                  </td>
                  <td className="py-2 pr-3">
                    {OPEN_STATUSES.has(order.status) ? (
                      <button
                        type="button"
                        onClick={() => void handleCancel(order.order_id)}
                        disabled={cancelingId === order.order_id}
                        className="rounded-md border px-2 py-0.5 text-xs disabled:opacity-50"
                      >
                        {cancelingId === order.order_id ? '取消中…' : '取消'}
                      </button>
                    ) : (
                      <span className="text-xs text-muted-foreground">
                        {order.termination_reason ?? '—'}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        配置延迟为模拟参数；实际模拟延迟 = 实际执行 − 提交时间；调度滞后 = 实际执行 − 计划执行，
        反映模拟调度粒度，两者均由服务端记录。
      </p>
    </section>
  )
}
