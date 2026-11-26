import { NavLink, Outlet } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { EnvironmentGate } from '@/bootstrap/EnvironmentGate'
import { connectionDisplay, useConnectionStore } from '@/state/connectionStore'

const NAV_ITEMS = [
  { to: '/market', label: '行情' },
  { to: '/trading', label: '交易' },
  { to: '/orders', label: '订单' },
  { to: '/executions', label: '成交' },
  { to: '/account', label: '账户' },
] as const

const STATUS_LABEL: Record<string, string> = {
  idle: '未连接',
  connecting: '连接中…',
  online: '实时已连接',
  resync: '同步中…',
  offline: '离线（自动重连）',
}

const STATUS_CLASS: Record<string, string> = {
  idle: 'bg-muted text-muted-foreground',
  connecting: 'bg-amber-100 text-amber-800',
  online: 'bg-emerald-100 text-emerald-800',
  resync: 'bg-sky-100 text-sky-800',
  offline: 'bg-red-100 text-red-800',
}

function ConnectionBadge() {
  const status = useConnectionStore((state) => state.status)
  const resyncReason = useConnectionStore((state) => state.resyncReason)
  const display = connectionDisplay(status)
  return (
    <span
      className={cn('rounded-full px-2 py-0.5 text-xs font-medium', STATUS_CLASS[display])}
      title={resyncReason ?? undefined}
    >
      {STATUS_LABEL[display]}
    </span>
  )
}

function AppLayout() {
  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <header className="border-b">
        <div className="mx-auto flex max-w-7xl items-center gap-6 px-4 py-3">
          <span className="text-sm font-semibold tracking-tight">Crypto Lab</span>
          <nav className="flex items-center gap-1" aria-label="主导航">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  cn(
                    'rounded-md px-3 py-1.5 text-sm transition-colors',
                    isActive
                      ? 'bg-accent font-medium'
                      : 'text-muted-foreground hover:bg-accent/50'
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <span className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
            <ConnectionBadge />
          </span>
        </div>
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">
        <EnvironmentGate>
          <Outlet />
        </EnvironmentGate>
      </main>
      <footer className="border-t">
        <p className="mx-auto max-w-7xl px-4 py-3 text-xs text-muted-foreground">
          模拟交易声明：本系统仅使用虚拟资金进行模拟交易，不连接真实账户、不提交真实订单、
          不构成任何投资建议或收益保证。行情数据来自 OKX 公共接口，仅供参考与学习。
        </p>
      </footer>
    </div>
  )
}

export default AppLayout
