import { NavLink, Outlet } from 'react-router-dom'
import { cn } from '@/shared/lib/utils'
import { Badge, Button, StatusDot } from '@/shared/ui'
import { connectionDisplay, useConnectionStore } from './connectionStore'
import { EnvironmentGate } from './EnvironmentGate'
import { useSessionStore } from './sessionStore'
import { useMarketStore } from '@/features/market/marketStore'

const STATUS_LABEL: Record<string, string> = {
  idle: '未连接',
  connecting: '连接中…',
  online: '已连接',
  resync: '同步中…',
  offline: '离线',
}

function EnvironmentSelector() {
  const session = useSessionStore((state) => state.session)
  if (session === null) return null
  return (
    <span
      className="numeric text-xs text-ink-muted"
      title={`模拟环境 ${session.environmentId} · 账户 ${session.accountId}`}
    >
      {session.environmentId.slice(0, 12)}…
    </span>
  )
}

function ConnectionBadge() {
  const status = useConnectionStore((state) => state.status)
  const resyncReason = useConnectionStore((state) => state.resyncReason)
  const display = connectionDisplay(status)
  return (
    <Badge tone={display === 'online' ? 'positive' : display === 'offline' || display === 'idle' ? 'negative' : 'info'} title={resyncReason ?? undefined}>
      {STATUS_LABEL[display]}
    </Badge>
  )
}

export function AppLayout() {
  const clearSession = useSessionStore((state) => state.clearSession)
  const quality = useMarketStore((state) => state.quality['okx:SPOT:BTC/USDT'])
  const lastEventTsMs = useConnectionStore((state) => state.lastEventTsMs)
  const status = useConnectionStore((state) => state.status)

  return (
    <>
      <div className="desktop-shell flex h-screen flex-col">
        {/* Top Navigation — 48px (docs/12 §6.1) */}
        <header className="flex h-12 shrink-0 items-center gap-6 border-b border-line bg-surface px-4">
          <span className="text-sm font-semibold tracking-tight text-brand">Crypto Lab</span>
          <nav className="flex items-center gap-1" aria-label="主导航">
            {/* Per docs/12 §5.2: only implemented pages get nav entries.
                Markets appears in Task 1.12.11. */}
            <NavLink
              to="/trading"
              className={({ isActive }) =>
                cn(
                  'rounded-[6px] px-3 py-1.5 text-sm transition-colors duration-150',
                  isActive ? 'bg-elevated font-medium text-brand' : 'text-ink-secondary hover:bg-elevated/60',
                )
              }
            >
              交易
            </NavLink>
            <NavLink
              to="/overview"
              className={({ isActive }) =>
                cn(
                  'rounded-[6px] px-3 py-1.5 text-sm transition-colors duration-150',
                  isActive ? 'bg-elevated font-medium text-brand' : 'text-ink-secondary hover:bg-elevated/60',
                )
              }
            >
              总览
            </NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <EnvironmentSelector />
            {/* Paper Trading identity (docs/12 §6.2): stable and restrained. */}
            <Badge tone="brand">Paper Trading</Badge>
            <ConnectionBadge />
            {/* Settings entry appears with the Settings page (Task 1.12.11). */}
            <Button
              variant="ghost"
              size="compact"
              onClick={() => {
                // Session reset lives here until the Settings page exists.
                clearSession()
              }}
              title="重置本地会话"
            >
              重置
            </Button>
          </div>
        </header>

        <main className="min-h-0 flex-1">
          <EnvironmentGate>
            <Outlet />
          </EnvironmentGate>
        </main>

        {/* Status Bar — 24px (docs/12 §6.3) */}
        <footer className="flex h-6 shrink-0 items-center gap-5 border-t border-line bg-surface px-4 text-[11px] text-ink-muted">
          <StatusDot
            tone={status === 'subscribed' || status === 'ready' ? 'positive' : 'neutral'}
            label={`Feed ${status === 'subscribed' ? '正常' : status === 'closed' ? '中断' : '等待'}`}
          />
          <StatusDot
            tone={quality === undefined || quality.status === 'VALID' ? 'positive' : 'warning'}
            label={`行情质量 ${quality?.status ?? '等待'}`}
          />
          <span className="numeric" title="最近行情接收时间">
            最近行情 {lastEventTsMs !== null ? new Date(lastEventTsMs).toLocaleTimeString('zh-CN', { hour12: false }) : '—'}
          </span>
          <StatusDot
            tone={status === 'subscribed' ? 'positive' : 'warning'}
            label={`WebSocket ${STATUS_LABEL[connectionDisplay(status)]}`}
          />
          <span>账户同步 {status === 'subscribed' ? '已同步' : '进行中'}</span>
          <span className="ml-auto">时区：本地（{Intl.DateTimeFormat().resolvedOptions().timeZone}）</span>
        </footer>
      </div>

      {/* Desktop-only guard (docs/12 §21). */}
      <div className="min-viewport-hint">
        <p className="text-sm text-ink">Crypto Lab 桌面交易工作台</p>
        <p className="text-xs text-ink-muted">
          本系统面向桌面浏览器设计，最小支持视口宽度 1280px。请使用桌面浏览器窗口访问。
        </p>
      </div>
    </>
  )
}
