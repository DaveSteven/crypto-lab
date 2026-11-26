import { NavLink, Outlet } from 'react-router-dom'
import { cn } from '@/lib/utils'

const NAV_ITEMS = [
  { to: '/market', label: '行情' },
  { to: '/trading', label: '交易' },
  { to: '/orders', label: '订单' },
  { to: '/executions', label: '成交' },
  { to: '/account', label: '账户' },
] as const

function AppLayout() {
  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <header className="border-b">
        <div className="mx-auto flex max-w-7xl items-center gap-6 px-4 py-3">
          <span className="text-sm font-semibold tracking-tight">Crypto Lab</span>
          <nav className="flex items-center gap-1">
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
          <span className="ml-auto text-xs text-muted-foreground">
            连接状态（1.12.3 接入）
          </span>
        </div>
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">
        <Outlet />
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
