import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useSessionStore } from '@/app/sessionStore'
import { ApiError, RestClient } from '@/shared/api/rest'
import type { TradingJournal } from '@/shared/api/schemas'
import { formatAmount, formatFee, formatPrice, formatQuantity } from '@/shared/lib/format'
import { Badge, Button, EmptyState, Input, Select } from '@/shared/ui'

const rest = new RestClient()

const INCOMPLETE_REASON: Record<string, string> = {
  NO_LINKED_ORDERS: '尚未关联订单',
  NO_LINKED_EXECUTIONS: '尚无关联成交',
  LINKED_BASE_QUANTITY_NOT_CLOSED: '关联成交的基础资产净数量尚未归零',
  ACTIVE_LINKED_ORDERS: '仍有关联订单处于活动状态',
}

export function JournalAssociations({ journal, onUpdated }: { journal: TradingJournal; onUpdated: () => void }) {
  const session = useSessionStore((state) => state.session)!
  const [selectedOrderId, setSelectedOrderId] = useState('')
  const [unlinkReason, setUnlinkReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const orders = useQuery({
    queryKey: ['journal-order-candidates', session.environmentId, session.accountId],
    queryFn: () => rest.listOrders(session.environmentId, { account_id: session.accountId, limit: 200 }),
  })
  const linkedIds = useMemo(() => new Set((journal.linked_orders ?? []).map((order) => order.order_id)), [journal.linked_orders])
  const candidates = (orders.data ?? []).filter((order) => order.instrument_id === journal.instrument_id && !linkedIds.has(order.order_id))
  const canLink = journal.status === 'READY' || journal.status === 'ACTIVE'

  async function link() {
    if (!selectedOrderId || busy) return
    setBusy(true)
    setMessage(null)
    try {
      await rest.linkJournalOrder(session.environmentId, session.accountId, journal.journal_id, selectedOrderId, journal.version)
      setSelectedOrderId('')
      setMessage('订单关联成功；该订单的后续部分成交会自动纳入。')
      onUpdated()
      await orders.refetch()
    } catch (reason) {
      setMessage(errorMessage('关联失败', reason))
    } finally {
      setBusy(false)
    }
  }

  async function unlink(orderId: string) {
    if (!unlinkReason.trim() || busy) return
    setBusy(true)
    setMessage(null)
    try {
      await rest.unlinkJournalOrder(session.environmentId, session.accountId, journal.journal_id, orderId, journal.version, unlinkReason.trim())
      setUnlinkReason('')
      setMessage('主观归属已解除；订单与成交事实仍完整保留。')
      onUpdated()
      await orders.refetch()
    } catch (reason) {
      setMessage(errorMessage('解除关联失败', reason))
    } finally {
      setBusy(false)
    }
  }

  const metrics = journal.metrics
  return (
    <div className="space-y-4">
      {canLink && (
        <div className="space-y-2 rounded-[6px] border border-line p-3">
          <div className="text-[12px] font-medium text-ink">关联同账户、同品种订单</div>
          <Select value={selectedOrderId} onChange={(event) => setSelectedOrderId(event.target.value)} disabled={orders.isPending || busy}>
            <option value="">{candidates.length === 0 ? '暂无可关联订单' : '选择订单'}</option>
            {candidates.map((order) => <option key={order.order_id} value={order.order_id}>{order.side} · {order.order_type} · {formatQuantity(order.quantity, order.instrument_id)} · {order.order_id.slice(0, 8)}…</option>)}
          </Select>
          <Button variant="outline" onClick={() => void link()} disabled={!selectedOrderId || busy}>关联订单</Button>
        </div>
      )}

      {(journal.linked_orders ?? []).length === 0 ? <EmptyState message="尚未关联真实模拟订单；系统不会推测或伪造成交结果。" /> : (
        <div className="space-y-2">
          {(journal.linked_orders ?? []).map((order) => {
            const fills = (journal.linked_executions ?? []).filter((fill) => fill.order_id === order.order_id)
            return <div key={order.order_id} className="rounded-[6px] border border-line p-3 text-[12px]">
              <div className="flex items-center justify-between gap-2"><span className="numeric font-medium text-ink">{order.order_id.slice(0, 12)}…</span><Badge tone={order.status === 'FILLED' ? 'positive' : 'neutral'}>{order.status}</Badge></div>
              <div className="mt-1 text-ink-secondary">{order.side} · {order.order_type} · {formatQuantity(order.quantity, order.instrument_id)} BTC</div>
              {fills.map((fill) => <div key={fill.execution_id} className="mt-2 border-t border-line pt-2 text-ink-muted">成交 {formatQuantity(fill.quantity, fill.instrument_id)} @ {formatPrice(fill.price, fill.instrument_id)} · 手续费 {formatFee(fill.fee_amount)} {fill.fee_asset}</div>)}
              <div className="mt-2 flex gap-2"><Input aria-label="解除关联原因" placeholder="解除原因（必填）" value={unlinkReason} onChange={(event) => setUnlinkReason(event.target.value)} /><Button variant="outline" onClick={() => void unlink(order.order_id)} disabled={!unlinkReason.trim() || busy}>解除</Button></div>
            </div>
          })}
        </div>
      )}

      {metrics && <div className="rounded-[6px] bg-elevated p-3 text-[12px]">
        <div className="flex items-center justify-between"><span className="font-medium text-ink">关联成交归因的已实现盈亏</span><Badge tone={metrics.trade_complete ? 'positive' : 'neutral'}>{metrics.trade_complete ? '客观交易已完成' : '尚未完成'}</Badge></div>
        {metrics.status === 'UNAVAILABLE' ? <p className="mt-2 text-warning">当前无法可靠重建：{metrics.reason ?? '未知原因'}</p> : <>
          <div className="mt-2 space-y-1">{Object.entries(metrics.attributed_realized_pnl_by_currency ?? {}).map(([asset, value]) => <div key={asset} className="flex justify-between"><span className="text-ink-muted">已实现盈亏</span><span className="numeric text-ink">{formatAmount(value)} {asset}</span></div>)}</div>
          <div className="mt-1 space-y-1">{Object.entries(metrics.fees_by_asset ?? {}).map(([asset, value]) => <div key={asset} className="flex justify-between"><span className="text-ink-muted">关联成交手续费</span><span className="numeric text-ink">{formatFee(value)} {asset}</span></div>)}</div>
          {(metrics.incomplete_reasons ?? []).map((reason) => <p key={reason} className="mt-1 text-ink-muted">· {INCOMPLETE_REASON[reason] ?? reason}</p>)}
        </>}
        <p className="mt-2 leading-relaxed text-ink-muted">按账户完整成交历史与移动平均成本重放，仅归因关联卖出成交的已实现盈亏增量；其他历史库存可能影响成本。不提供缺乏可靠库存分配依据的日志未实现盈亏。</p>
      </div>}
      {message && <p role="status" className="text-[12px] text-info">{message}</p>}
    </div>
  )
}

function errorMessage(prefix: string, reason: unknown): string {
  return reason instanceof ApiError ? `${prefix}（${reason.code}）：${reason.message}` : `${prefix}：${reason instanceof Error ? reason.message : String(reason)}`
}
