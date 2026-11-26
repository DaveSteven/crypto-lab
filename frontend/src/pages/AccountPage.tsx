import { formatDecimal } from '@/lib/format'
import { useSessionStore } from '@/state/sessionStore'
import { useTradingStore } from '@/state/tradingStore'

export function AccountPage() {
  const session = useSessionStore((state) => state.session)
  const balances = useTradingStore((state) => state.balances)
  const positions = useTradingStore((state) => state.positions)
  const stateVersion = useTradingStore((state) => state.stateVersion)

  return (
    <section aria-labelledby="account-title" className="space-y-6">
      <div>
        <h1 id="account-title" className="text-lg font-semibold">
          账户
        </h1>
        {session !== null && (
          <p className="mt-1 text-xs text-muted-foreground">
            环境 {session.environmentId} · 账户 {session.accountId} · 一致性版本 {stateVersion}
          </p>
        )}
      </div>

      <div>
        <h2 className="mb-2 text-sm font-medium">余额（可用 / 冻结）</h2>
        {balances.length === 0 ? (
          <p className="text-sm text-muted-foreground">暂无余额记录。</p>
        ) : (
          <table className="w-full max-w-lg text-left text-sm">
            <caption className="sr-only">资产余额</caption>
            <thead>
              <tr className="border-b text-xs text-muted-foreground">
                <th className="py-2 pr-3">资产</th>
                <th className="py-2 pr-3">可用</th>
                <th className="py-2 pr-3">冻结</th>
              </tr>
            </thead>
            <tbody>
              {balances.map((balance) => (
                <tr key={balance.asset} className="border-b">
                  <td className="py-2 pr-3">{balance.asset}</td>
                  <td className="py-2 pr-3">{formatDecimal(balance.available)}</td>
                  <td className="py-2 pr-3">{formatDecimal(balance.locked)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div>
        <h2 className="mb-2 text-sm font-medium">持仓（移动平均成本法）</h2>
        {positions.length === 0 ? (
          <p className="text-sm text-muted-foreground">暂无持仓。</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">持仓投影</caption>
              <thead>
                <tr className="border-b text-xs text-muted-foreground">
                  <th className="py-2 pr-3">品种</th>
                  <th className="py-2 pr-3">数量</th>
                  <th className="py-2 pr-3">平均成本</th>
                  <th className="py-2 pr-3">成本基础</th>
                  <th className="py-2 pr-3">已实现盈亏</th>
                  <th className="py-2 pr-3">累计手续费</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((position) => (
                  <tr key={position.instrument_id} className="border-b">
                    <td className="py-2 pr-3">{position.instrument_id}</td>
                    <td className="py-2 pr-3">{formatDecimal(position.quantity)}</td>
                    <td className="py-2 pr-3">{formatDecimal(position.average_cost)}</td>
                    <td className="py-2 pr-3">{formatDecimal(position.cost_basis)}</td>
                    <td className="py-2 pr-3">{formatDecimal(position.realized_pnl)}</td>
                    <td className="py-2 pr-3">{formatDecimal(position.cumulative_fees)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <p className="text-xs text-muted-foreground">
        全部资金与持仓均为模拟数据；余额权威来源为资金流水（Ledger），持仓权威来源为成交历史重建。
        估值及盈亏展示仅供参考，不构成任何收益保证，数据时间以服务端为准。
      </p>
    </section>
  )
}
