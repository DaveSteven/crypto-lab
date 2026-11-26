import { formatDecimal, formatTime } from '@/lib/format'
import { useTradingStore } from '@/state/tradingStore'

export function ExecutionsPage() {
  const executions = useTradingStore((state) => state.executions)
  const sorted = [...executions].sort((a, b) => b.executed_ts_ms - a.executed_ts_ms)

  return (
    <section aria-labelledby="executions-title" className="space-y-3">
      <h1 id="executions-title" className="text-lg font-semibold">
        成交记录
      </h1>
      {sorted.length === 0 ? (
        <p className="text-sm text-muted-foreground">暂无成交。</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">模拟成交记录（Fill History，只读）</caption>
            <thead>
              <tr className="border-b text-xs text-muted-foreground">
                <th className="py-2 pr-3">成交时间</th>
                <th className="py-2 pr-3">品种</th>
                <th className="py-2 pr-3">方向</th>
                <th className="py-2 pr-3">成交价</th>
                <th className="py-2 pr-3">数量</th>
                <th className="py-2 pr-3">成交额</th>
                <th className="py-2 pr-3">手续费</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((execution) => (
                <tr key={execution.execution_id} className="border-b">
                  <td className="py-2 pr-3">{formatTime(execution.executed_ts_ms)}</td>
                  <td className="py-2 pr-3">{execution.instrument_id}</td>
                  <td className="py-2 pr-3">{execution.side === 'BUY' ? '买入' : '卖出'}</td>
                  <td className="py-2 pr-3">{formatDecimal(execution.price)}</td>
                  <td className="py-2 pr-3">{formatDecimal(execution.quantity)}</td>
                  <td className="py-2 pr-3">{formatDecimal(execution.quote_amount)}</td>
                  <td className="py-2 pr-3">
                    {formatDecimal(execution.fee_amount)} {execution.fee_asset}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        成交记录为服务端 Fill History 投影，只读；成交价格与手续费由订单簿撮合与费率配置（模拟配置）决定。
      </p>
    </section>
  )
}
