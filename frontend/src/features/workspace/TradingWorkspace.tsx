import { useEffect, useMemo, useState } from 'react'
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels'
import { useInstrumentStore } from '@/features/market/instrumentStore'
import { MarketDepthPanel } from '@/features/market/MarketDepthPanel'
import { MarketChartPanel } from '@/features/market/MarketChartPanel'
import { OrderEntryPanel } from '@/features/trading/OrderEntryPanel'
import { OrdersTable } from '@/features/trading/OrdersTable'
import { ExecutionsTable } from '@/features/trading/ExecutionsTable'
import { AccountPanel } from '@/features/account/AccountPanel'
import { ExecutionDetailDrawer } from '@/features/trading/ExecutionDetailDrawer'
import { OPEN_STATUSES, SYNC_LABEL, accountSyncState } from '@/features/trading/orderStatus'
import { connectionDisplay, useConnectionStore } from '@/app/connectionStore'
import { Badge, Button, Tabs } from '@/shared/ui'
import { useTradingStore } from '@/features/trading/tradingStore'

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
  const instrumentId = useInstrumentStore((state) => state.instrumentId)
  const connectionStatus = useConnectionStore((state) => state.status)
  const sync = accountSyncState(connectionDisplay(connectionStatus))
  const [activityTab, setActivityTab] = useState<ActivityTab>('open')
  const orders = useTradingStore((state) => state.orders)
  const [activityCollapsed, setActivityCollapsed] = useState(
    () => localStorage.getItem('trading-activity.collapsed') === 'true',
  )
  const openCount = orders.filter((order) => OPEN_STATUSES.has(order.status)).length
  const tabs = useMemo(
    () => ACTIVITY_TABS.map((item) => item.value === 'open' ? { ...item, label: `当前委托 ${openCount}` } : item),
    [openCount],
  )
  useEffect(() => {
    localStorage.setItem('trading-activity.collapsed', String(activityCollapsed))
  }, [activityCollapsed])

  return (
    <div className="relative h-full min-h-0 p-1">
      <ExecutionDetailDrawer />
      <PanelGroup direction="vertical" autoSaveId="trading-workspace.v1" className="h-full">
        {/* Main three-column area — chart 54% / book-trades 21% / entry 25% (§7.2). */}
        <Panel defaultSize={activityCollapsed ? 100 : 72} minSize={40}>
          <PanelGroup
            direction="horizontal"
            autoSaveId="trading-main.v1"
            className="h-full"
          >
            <Panel defaultSize={54} minSize={30}>
              <MarketChartPanel />
            </Panel>
            <PanelResizeHandle aria-label="调整图表与订单簿宽度" className="workspace-resize-handle h-full w-1" />
            <Panel defaultSize={21} minSize={16}>
              <MarketDepthPanel />
            </Panel>
            <PanelResizeHandle aria-label="调整订单簿与下单面板宽度" className="workspace-resize-handle h-full w-1" />
            <Panel defaultSize={25} minSize={20}>
              {/* Keyed by instrument: switching pair discards drafts (prices don't carry over). */}
              <OrderEntryPanel key={instrumentId} />
            </Panel>
          </PanelGroup>
        </Panel>

        {!activityCollapsed && <PanelResizeHandle aria-label="调整行情区与账户活动面板高度" className="workspace-resize-handle h-1" />}

        {/* Account Activity Panel — default 28% (docs/12 §7.2/§12). */}
        {!activityCollapsed && <Panel defaultSize={28} minSize={10}>
          <section
            aria-label="账户活动"
            className="flex h-full flex-col overflow-hidden rounded-[4px] border border-line bg-surface"
          >
            <header className="flex h-9 shrink-0 items-center border-b border-line px-2">
              <Tabs items={tabs} value={activityTab} onChange={setActivityTab} />
              <Button variant="ghost" size="compact" className="ml-auto" onClick={() => setActivityCollapsed(true)}>收起面板</Button>
              <Badge tone={sync === 'synced' ? 'positive' : 'warning'} className="ml-2" data-testid="account-sync">
                {SYNC_LABEL[sync]}
              </Badge>
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
        </Panel>}
      </PanelGroup>
      {activityCollapsed && (
        <Button variant="secondary" size="compact" className="absolute bottom-2 left-2 z-20" onClick={() => setActivityCollapsed(false)}>
          展开账户活动 · 当前委托 {openCount}
        </Button>
      )}
    </div>
  )
}
