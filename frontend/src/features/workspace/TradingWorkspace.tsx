import { useState } from 'react'
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels'
import { MarketChartPanel } from '@/features/market/MarketChartPanel'
import { OrderEntryPanel } from '@/features/trading/OrderEntryPanel'
import { OrdersTable } from '@/features/trading/OrdersTable'
import { ExecutionsTable } from '@/features/trading/ExecutionsTable'
import { AccountPanel } from '@/features/account/AccountPanel'
import { Badge, EmptyState, Tabs } from '@/shared/ui'

/**
 * Trading workspace (docs/12 §7): three-column resizable area over a
 * bottom Account Activity Panel.
 *
 * Layout persistence: react-resizable-panels `autoSaveId` keeps the
 * versioned key in localStorage ("trading-workspace.v1"); a corrupted or
 * foreign key simply yields defaults. Keyboard resize is built into the
 * PanelResizeHandle (arrow keys).
 */
type ActivityTab = 'open' | 'history' | 'executions' | 'balances' | 'positions'

const ACTIVITY_TABS = [
  { value: 'open', label: '当前委托' },
  { value: 'history', label: '历史订单' },
  { value: 'executions', label: '成交记录' },
  { value: 'balances', label: '资产余额' },
  { value: 'positions', label: '持仓盈亏' },
] as const

export function TradingWorkspace() {
  const [activityTab, setActivityTab] = useState<ActivityTab>('open')

  return (
    <div className="h-full min-h-0 p-1">
      <PanelGroup direction="vertical" autoSaveId="trading-workspace.v1" className="h-full">
        {/* Main three-column area — chart 54% / book-trades 21% / entry 25% (§7.2). */}
        <Panel defaultSize={72} minSize={40}>
          <PanelGroup
            direction="horizontal"
            autoSaveId="trading-main.v1"
            className="h-full"
          >
            <Panel defaultSize={54} minSize={30}>
              <MarketChartPanel />
            </Panel>
            <PanelResizeHandle className="h-full w-1 rounded hover:bg-brand/20 data-[resize-handle-state]:bg-brand/30 focus-visible:outline-2 focus-visible:outline-brand" />
            <Panel defaultSize={21} minSize={16}>
              {/* Order Book / Market Trades tabs arrive with Task 1.12.7;
                  the empty state is deliberate (docs/12 §5.2, §22). */}
              <section
                aria-label="订单簿与最新成交"
                className="flex h-full flex-col overflow-hidden rounded-[4px] border border-line bg-surface"
              >
                <header className="flex h-9 shrink-0 items-center border-b border-line px-3">
                  <span className="text-sm font-medium text-ink">订单簿</span>
                  <Badge tone="neutral" className="ml-2">
                    1.12.7
                  </Badge>
                </header>
                <EmptyState message="订单簿面板将在 Task 1.12.7 接入（数据通道已就绪）。" />
              </section>
            </Panel>
            <PanelResizeHandle className="h-full w-1 rounded hover:bg-brand/20 data-[resize-handle-state]:bg-brand/30 focus-visible:outline-2 focus-visible:outline-brand" />
            <Panel defaultSize={25} minSize={20}>
              <OrderEntryPanel />
            </Panel>
          </PanelGroup>
        </Panel>

        <PanelResizeHandle className="h-1 rounded hover:bg-brand/20 focus-visible:outline-2 focus-visible:outline-brand" />

        {/* Account Activity Panel — default 28% (docs/12 §7.2/§12). */}
        <Panel defaultSize={28} minSize={10}>
          <section
            aria-label="账户活动"
            className="flex h-full flex-col overflow-hidden rounded-[4px] border border-line bg-surface"
          >
            <header className="flex h-9 shrink-0 items-center border-b border-line px-2">
              <Tabs items={[...ACTIVITY_TABS]} value={activityTab} onChange={setActivityTab} />
            </header>
            <div className="min-h-0 flex-1 overflow-auto">
              {activityTab === 'open' && <OrdersTable filter="open" emptyMessage="暂无当前委托。" />}
              {activityTab === 'history' && (
                <OrdersTable filter="history" emptyMessage="暂无历史订单。" />
              )}
              {activityTab === 'executions' && <ExecutionsTable compact />}
              {activityTab === 'balances' && <AccountPanel view="balances" />}
              {activityTab === 'positions' && <AccountPanel view="positions" />}
            </div>
          </section>
        </Panel>
      </PanelGroup>
    </div>
  )
}
