import { useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { RestClient } from '@/shared/api/rest'
import { enterSession, switchEnvironment } from '@/app/environmentSwitch'
import { useSessionStore } from '@/app/sessionStore'
import { connectionDisplay, useConnectionStore } from '@/app/connectionStore'
import { useMarketStore } from '@/features/market/marketStore'
import { REFERENCE_FEE_RATE, REFERENCE_FEE_SCHEDULE } from '@/features/trading/orderPreview'
import { Badge, Button, EmptyState, Input, Label, PageContainer, PageHeader, Panel } from '@/shared/ui'

const rest = new RestClient()
const NOT_PROVIDED = '后端暂未提供'

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 py-1 text-xs">
      <dt className="text-ink-muted">{label}</dt>
      <dd className="numeric text-right text-ink">{value}</dd>
    </div>
  )
}

function EnvironmentSection() {
  const queryClient = useQueryClient()
  const session = useSessionStore((state) => state.session)
  const environments = useQuery({ queryKey: ['environments'], queryFn: () => rest.listEnvironments(50) })
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [form, setForm] = useState({ name: '', account: 'Paper Account', amount: '10000' })

  async function handleSwitch(environmentId: string) {
    setBusy(environmentId)
    setMessage(null)
    try {
      await switchEnvironment(environmentId, queryClient)
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusy(null)
    }
  }

  async function handleCreate(event: FormEvent) {
    event.preventDefault()
    if (busy !== null) return
    setBusy('create')
    setMessage(null)
    try {
      const environment = await rest.createEnvironment(form.name)
      const account = await rest.createAccount(environment.environment_id, {
        exchange_id: 'okx',
        name: form.account,
        initial_asset: 'USDT',
        initial_amount: form.amount,
      })
      enterSession(environment.environment_id, account.account_id, queryClient)
      setForm({ ...form, name: '' })
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusy(null)
    }
  }

  return (
    <Panel title="模拟环境">
      <div className="space-y-3 p-3">
        {environments.isPending ? (
          <EmptyState message="加载中…" />
        ) : environments.isError ? (
          <p role="alert" className="text-xs text-negative">无法获取环境列表。</p>
        ) : (
          <ul className="divide-y divide-line text-xs" aria-label="模拟环境列表">
            {environments.data.map((environment) => {
              const current = environment.environment_id === session?.environmentId
              return (
                <li key={environment.environment_id} className="flex items-center gap-3 py-2">
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium text-ink">{environment.name}</div>
                    <details className="mt-1 text-[12px] text-ink-muted"><summary className="cursor-pointer">技术详情</summary><div className="numeric mt-1 break-all">环境标识：{environment.environment_id}</div></details>
                  </div>
                  {current ? (
                    <Badge tone="brand">当前环境</Badge>
                  ) : (
                    <Button
                      size="compact"
                      variant="outline"
                      disabled={busy !== null}
                      onClick={() => void handleSwitch(environment.environment_id)}
                    >
                      {busy === environment.environment_id ? '切换中…' : '切换到此环境'}
                    </Button>
                  )}
                </li>
              )
            })}
          </ul>
        )}
        {message !== null && (
          <p role="alert" className="text-xs text-negative">{message}</p>
        )}
        <form className="space-y-2 border-t border-line pt-3" onSubmit={(event) => void handleCreate(event)}>
          <h3 className="text-xs font-medium text-ink-secondary">创建新环境（含一个模拟账户，创建后自动切换）</h3>
          <Label>
            新环境名称
            <Input className="mt-1" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </Label>
          <div className="grid grid-cols-2 gap-2">
            <Label>
              账户名称
              <Input className="mt-1" value={form.account} onChange={(e) => setForm({ ...form, account: e.target.value })} required />
            </Label>
            <Label>
              初始虚拟资金（USDT）
              <Input className="mt-1 numeric" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} required inputMode="decimal" />
            </Label>
          </div>
          <Button type="submit" size="compact" variant="primary" disabled={busy !== null}>
            {busy === 'create' ? '创建中…' : '创建并切换'}
          </Button>
        </form>
        <p className="text-[11px] text-ink-muted">
          当前 Contract 不提供删除或重置环境的接口，因此这里不提供这些操作。
        </p>
      </div>
    </Panel>
  )
}

function AccountSection() {
  const session = useSessionStore((state) => state.session)
  const accounts = useQuery({
    queryKey: ['accounts', session?.environmentId],
    queryFn: () => rest.listAccounts(session?.environmentId ?? '', 50),
    enabled: session !== null,
  })
  const account = accounts.data?.find((item) => item.account_id === session?.accountId)
  return (
    <Panel title="账户">
      <dl className="p-3">
        <Field label="当前账户" value={account?.name ?? '--'} />
        <Field label="默认执行延迟" value="尚未实现账户级持久化；当前每笔订单默认使用标准（100 ms）" />
        <Field label="手续费配置" value="实际费用由服务端撮合时决定" />
        <Field label="本地预览参考" value={`${REFERENCE_FEE_RATE}（${REFERENCE_FEE_SCHEDULE}），仅用于下单前估算`} />
      </dl>
      <details className="mx-3 mb-3 rounded-[6px] border border-line p-3 text-[12px] text-ink-muted"><summary className="cursor-pointer text-ink-secondary">账户技术详情</summary><div className="numeric mt-2 break-all">账户标识：{session?.accountId ?? '—'}</div></details>
      <p className="px-3 pb-3 text-[11px] text-ink-muted">已结算的流水与成交记录不可在此修改。</p>
    </Panel>
  )
}

function WorkspaceSection() {
  const clearSession = useSessionStore((state) => state.clearSession)
  const [done, setDone] = useState(false)

  function resetLayout() {
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith('react-resizable-panels:')) localStorage.removeItem(key)
    }
    setDone(true)
  }

  return (
    <Panel title="工作区">
      <div className="space-y-2 p-3 text-xs">
        <Field label="显示时区" value={Intl.DateTimeFormat().resolvedOptions().timeZone} />
        <div className="flex items-center gap-2">
          <Button size="compact" variant="outline" onClick={resetLayout}>
            恢复默认面板布局
          </Button>
          {done && (
            <span role="status" className="text-ink-secondary">
              已清除保存的布局，重新进入交易页即恢复默认。
            </span>
          )}
        </div>
        <div className="border-t border-line pt-2">
          <Button
            size="compact"
            variant="outline"
            onClick={() => {
              if (window.confirm('这只会清除浏览器中保存的会话选择，不会删除服务端的任何模拟数据。继续？')) clearSession()
            }}
          >
            清除本地会话选择
          </Button>
        </div>
      </div>
    </Panel>
  )
}

function SystemSection() {
  const status = useConnectionStore((state) => state.status)
  const quality = useMarketStore((state) => state.quality)
  const tickers = useMarketStore((state) => state.tickers)
  const api = useQuery({ queryKey: ['health-ready'], queryFn: () => rest.healthReady(), refetchInterval: 10_000, retry: 0 })
  const instruments = useQuery({ queryKey: ['market-instruments-settings'], queryFn: () => rest.marketInstruments() })
  const recovery = useQuery({ queryKey: ['recovery'], queryFn: () => rest.recoveryStatus(), refetchInterval: 15_000, retry: 0 })
  const failed = Object.entries(recovery.data?.failed ?? {})
  return (
    <Panel title="系统状态">
      <dl className="p-3">
        <Field label="API" value={api.isError ? <Badge tone="negative">不可用</Badge> : api.data ? <Badge tone="positive">就绪</Badge> : '检查中…'} />
        <Field label="WebSocket" value={connectionDisplay(status)} />
        <Field
          label="Exchange Feed"
          value={instruments.data === undefined ? '--' : instruments.data.feed_enabled ? '已启用（OKX 公共行情）' : '未启用'}
        />
        <Field
          label="行情品种"
          value={(instruments.data?.items ?? []).map((item) => `${item.base_asset}/${item.quote_asset}`).join('、') || '--'}
        />
        <Field label="K 线周期" value="1m 常驻；其他周期按页面需求动态订阅" />
        <Field
          label="数据质量"
          value={
            Object.keys(tickers).length === 0
              ? '等待行情'
              : Object.keys(tickers)
                  .map((id) => `${id.split(':')[2]} ${quality[id]?.status ?? 'VALID'}`)
                  .join(' · ')
          }
        />
        <Field
          label="启动恢复"
          value={
            recovery.isError
              ? '无法读取'
              : failed.length === 0
                ? `已恢复 ${recovery.data?.recovered.length ?? 0} 个环境`
                : <Badge tone="negative">{failed.length} 个环境恢复失败</Badge>
          }
        />
        <Field label="Scheduler 配置" value={NOT_PROVIDED} />
      </dl>
      {failed.length > 0 && (
        <ul role="alert" className="px-3 pb-3 text-[11px] text-negative">
          {failed.map(([id, reason]) => (
            <li key={id}>{id}：{reason}</li>
          ))}
        </ul>
      )}
    </Panel>
  )
}

function TradingSection() {
  return <Panel title="交易设置"><div className="space-y-3 p-4 text-[13px]"><div className="rounded-[6px] border border-line bg-canvas/40 p-4"><h3 className="font-medium text-ink">订单执行延迟</h3><p className="mt-1 text-ink-secondary">账户默认值的后端持久化尚未完成。当前下单面板默认选择“标准（100 ms）”，每笔订单可单独覆盖。</p></div><div className="rounded-[6px] border border-line bg-canvas/40 p-4"><h3 className="font-medium text-ink">手续费</h3><p className="mt-1 text-ink-secondary">实际 Maker/Taker 手续费由服务端配置和撮合结果决定。前端仅以 {REFERENCE_FEE_RATE} 作为预览参考，不会写入账户配置。</p></div></div></Panel>
}

/** Settings (docs/12 §17): only capabilities the backend actually offers. */
export function SettingsPage() {
  const [section, setSection] = useState<'environment' | 'account' | 'trading' | 'workspace' | 'system'>('environment')
  const sections = [
    ['environment', '模拟环境'],
    ['account', '账户配置'],
    ['trading', '交易设置'],
    ['workspace', '工作区'],
    ['system', '系统状态'],
  ] as const
  return (
    <PageContainer>
      <PageHeader title="设置" description="管理模拟环境、交易偏好与本地工作区；系统诊断信息单独展示。" />
      <div className="grid grid-cols-[220px_minmax(0,1fr)] gap-6">
        <nav aria-label="设置分类" className="self-start rounded-[6px] border border-line bg-surface p-2">
          {sections.map(([value, label]) => <button key={value} type="button" onClick={() => setSection(value)} className={`mb-1 flex h-10 w-full items-center rounded-[6px] px-3 text-left text-[14px] ${section === value ? 'bg-elevated font-medium text-brand' : 'text-ink-secondary hover:bg-elevated/60 hover:text-ink'}`}>{label}</button>)}
        </nav>
        <div className="min-w-0">
          {section === 'environment' && <EnvironmentSection />}
          {section === 'account' && <AccountSection />}
          {section === 'trading' && <TradingSection />}
          {section === 'workspace' && <WorkspaceSection />}
          {section === 'system' && <SystemSection />}
        </div>
      </div>
    </PageContainer>
  )
}
