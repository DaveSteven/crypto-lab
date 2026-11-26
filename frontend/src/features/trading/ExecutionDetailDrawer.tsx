import { formatFee, formatLatency, formatPrice, formatQuantity, formatTime, instrumentLabel } from '@/shared/lib/format'
import { Drawer, TermTip } from '@/shared/ui'
import { useDetailStore } from './detailStore'
import { useTradingStore } from './tradingStore'
import { fillSummary, remainingQuantity, statusLabel } from './orderStatus'

function Row({ label, value, tip }: { label: string; value: string; tip?: string }) {
  return (
    <div className="flex justify-between gap-4 py-0.5 text-xs">
      <dt className="text-ink-muted">{tip ? <TermTip term={label} description={tip} /> : label}</dt>
      <dd className="numeric break-all text-right text-ink">{value}</dd>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-4">
      <h3 className="mb-1 border-b border-line pb-1 text-xs font-medium text-ink-secondary">{title}</h3>
      <dl>{children}</dl>
    </section>
  )
}

const MISSING = '-- 后端暂未提供'

/** Execution Detail Drawer (docs/12 §14). Only fields the backend provides are shown;
 * the rest are explicitly marked rather than computed or invented. */
export function ExecutionDetailDrawer() {
  const { orderId, executionId, close } = useDetailStore()
  const order = useTradingStore((state) => state.orders.find((item) => item.order_id === orderId))
  const executions = useTradingStore((state) => state.executions)
  const fills = executions
    .filter((item) => item.order_id === orderId)
    .sort((a, b) => a.executed_ts_ms - b.executed_ts_ms)

  return (
    <Drawer open={orderId !== null} title="订单与成交详情" onClose={close}>
      {order === undefined ? (
        <p className="text-xs text-ink-muted">未找到该订单（可能尚未同步），请稍后刷新。</p>
      ) : (
        <>
          <Section title="基本信息">
            <Row label="订单 ID" value={order.order_id} />
            {executionId !== null && <Row label="成交 ID" value={executionId} />}
            <Row label="交易所 / 品种" value={`OKX / ${instrumentLabel(order.instrument_id)}`} />
            <Row label="方向 / 类型" value={`${order.side === 'BUY' ? '买入' : '卖出'} · ${order.order_type === 'MARKET' ? '市价' : '限价'} ${order.time_in_force}`} />
            <Row label="数量" value={formatQuantity(order.quantity, order.instrument_id)} />
            <Row label="已成交 / 剩余" value={`${formatQuantity(order.filled_quantity, order.instrument_id)} / ${formatQuantity(remainingQuantity(order), order.instrument_id)}`} />
            <Row label="状态" value={statusLabel(order.status)} />
            {fillSummary(order) !== null && <Row label="说明" value={fillSummary(order) ?? ''} />}
            {order.termination_reason && <Row label="终止原因" value={order.termination_reason} />}
            <Row label="提交时间" value={formatTime(order.submitted_ts_ms)} />
          </Section>

          <Section title="成交分析">
            <Row label="提交参考价" value={formatPrice(order.reference_price, order.instrument_id)} />
            <Row label="成交均价" value={formatPrice(order.average_fill_price, order.instrument_id)} />
            <Row label="累计成交额" value={formatFee(order.cumulative_quote_amount)} />
            <Row
              label="手续费（累计）"
              tip="交易所按成交额收取的费用，与滑点分开显示；滑点已包含在成交价格里，不重复计算。"
              value={`${formatFee(order.cumulative_fee)}（费率 ${formatQuantity(order.reserved_fee_rate)}，${order.fee_schedule_id ?? '--'}）`}
            />
            <Row label="Maker / Taker" value={MISSING} />
            <Row
              label="VWAP"
              tip="成交量加权平均价：按每一档实际成交量加权计算的平均成交价。"
              value={MISSING}
            />
            <Row
              label="滑点"
              tip="实际成交价与参考价之间的差距，来自订单簿深度不足或价格在延迟期间变化。"
              value={MISSING}
            />
          </Section>

          <Section title="延迟分析">
            <Row label="配置延迟" value={formatLatency(order.configured_latency_ms)} />
            <Row label="计划执行时间" value={formatTime(order.scheduled_execution_ts_ms)} />
            <Row label="实际执行时间" value={formatTime(order.executed_ts_ms)} />
            <Row label="调度滞后" value={formatLatency(order.scheduler_lag_ms)} />
            <Row label="实际模拟延迟" value={formatLatency(order.actual_simulated_delay_ms)} />
            <p className="mt-1 text-[11px] text-ink-muted">
              实际模拟延迟是模拟撮合的等待时间，不等于真实交易所的网络延迟。
            </p>
          </Section>

          <Section title={`实际成交明细（${fills.length}）`}>
            {fills.length === 0 && <p className="text-xs text-ink-muted">暂无成交。</p>}
            {fills.map((fill) => (
              <div
                key={fill.execution_id}
                className={`mb-1 rounded-[6px] px-2 py-1 text-xs ${fill.execution_id === executionId ? 'bg-brand/10 ring-1 ring-brand' : 'bg-surface'}`}
              >
                <div className="numeric flex justify-between">
                  <span>{formatTime(fill.executed_ts_ms)}</span>
                  <span>
                    {formatQuantity(fill.quantity, order.instrument_id)} @ {formatPrice(fill.price, order.instrument_id)}
                  </span>
                </div>
                <div className="numeric flex justify-between text-ink-muted">
                  <span className="break-all">{fill.execution_id}</span>
                  <span>
                    {formatFee(fill.fee_amount)} {fill.fee_asset}
                  </span>
                </div>
              </div>
            ))}
          </Section>
        </>
      )}
    </Drawer>
  )
}
