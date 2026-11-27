import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useSessionStore } from '@/app/sessionStore'
import { RestClient } from '@/shared/api/rest'
import type { JournalStatus } from '@/shared/api/schemas'
import { instrumentLabel } from '@/shared/lib/format'
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Input,
  Label,
  PageContainer,
  PageHeader,
  Panel,
  Select,
} from '@/shared/ui'
import { formatJournalDate, JOURNAL_STATUS } from './journalDisplay'

const rest = new RestClient()
const STATUS_OPTIONS: Array<{ value: '' | JournalStatus; label: string }> = [
  { value: '', label: '全部状态' },
  ...Object.entries(JOURNAL_STATUS).map(([value, item]) => ({
    value: value as JournalStatus,
    label: item.label,
  })),
]

export function JournalListPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const session = useSessionStore((state) => state.session)!
  const [status, setStatus] = useState<'' | JournalStatus>('')
  const [instrumentFilter, setInstrumentFilter] = useState('')
  const instrument = instrumentFilter.trim()
    ? `okx:SPOT:${instrumentFilter.trim().toUpperCase()}`
    : ''
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState({
    title: '',
    instrumentId: 'okx:SPOT:BTC/USDT',
    timeframe: '1h',
  })

  const query = useQuery({
    queryKey: ['journals', session.environmentId, session.accountId, status, instrument],
    queryFn: () =>
      rest.listJournals(session.environmentId, session.accountId, {
        limit: 100,
        status: status || undefined,
        instrument_id: instrument || undefined,
      }),
  })
  const create = useMutation({
    mutationFn: () =>
      rest.createJournal(session.environmentId, session.accountId, {
        title: form.title.trim(),
        instrument_id: form.instrumentId,
        timeframe: form.timeframe || undefined,
      }),
    onSuccess: async (journal) => {
      await queryClient.invalidateQueries({ queryKey: ['journals', session.environmentId, session.accountId] })
      navigate(`/journal/${journal.journal_id}`)
    },
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    if (form.title.trim() && !create.isPending) create.mutate()
  }

  return (
    <PageContainer>
      <PageHeader
        title="交易日志"
        description="记录交易前计划、执行过程与复盘。日志不会修改订单、成交或账户资金。"
        actions={<Button variant="primary" onClick={() => setShowCreate((value) => !value)}>{showCreate ? '取消新建' : '新建交易日志'}</Button>}
      />

      {showCreate && (
        <Panel title="创建 Draft" className="mb-5" bodyClassName="p-4">
          <form className="grid grid-cols-[minmax(260px,2fr)_minmax(220px,1fr)_140px_auto] items-end gap-3" onSubmit={submit}>
            <Label>日志标题<Input className="mt-1" value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} maxLength={200} required autoFocus /></Label>
            <Label>主交易品种<Select className="mt-1" value={form.instrumentId} onChange={(event) => setForm({ ...form, instrumentId: event.target.value })}><option value="okx:SPOT:BTC/USDT">BTC/USDT · OKX Spot</option><option value="okx:SPOT:ETH/USDT">ETH/USDT · OKX Spot</option></Select></Label>
            <Label>观察周期<Select className="mt-1" value={form.timeframe} onChange={(event) => setForm({ ...form, timeframe: event.target.value })}><option value="15m">15 分钟</option><option value="1h">1 小时</option><option value="4h">4 小时</option><option value="1d">1 天</option></Select></Label>
            <Button type="submit" variant="primary" disabled={!form.title.trim() || create.isPending}>{create.isPending ? '创建中…' : '保存 Draft'}</Button>
          </form>
          {create.isError && <p role="alert" className="mt-3 text-[12px] text-negative">创建失败：{create.error.message}</p>}
        </Panel>
      )}

      <Panel
        title="日志记录"
        actions={<><Select aria-label="状态筛选" className="h-8 w-36 text-[13px]" value={status} onChange={(event) => setStatus(event.target.value as '' | JournalStatus)}>{STATUS_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</Select><Input aria-label="交易品种筛选" className="h-8 w-48 text-[13px]" placeholder="例如 BTC/USDT" value={instrumentFilter} onChange={(event) => setInstrumentFilter(event.target.value)} /></>}
      >
        {query.isPending ? <EmptyState message="正在加载交易日志…" /> : query.isError ? <ErrorState message="无法读取交易日志。" onRetry={() => void query.refetch()} /> : query.data.length === 0 ? <EmptyState message="暂无符合条件的交易日志。可以先创建一个 Draft，记录交易前的判断依据。" /> : (
          <table className="w-full text-left text-[13px]">
            <thead><tr className="border-b border-line text-[12px] text-ink-muted"><th className="px-4 py-2">标题</th><th className="py-2 pr-3">状态</th><th className="py-2 pr-3">主交易品种</th><th className="py-2 pr-3">观察周期</th><th className="py-2 pr-3">计划版本</th><th className="py-2 pr-4 text-right">最后更新</th></tr></thead>
            <tbody>{query.data.map((journal) => { const display = JOURNAL_STATUS[journal.status]; return <tr key={journal.journal_id} className="cursor-pointer border-b border-line/50 hover:bg-elevated/40" onClick={() => navigate(`/journal/${journal.journal_id}`)}><td className="px-4 py-3"><button type="button" className="font-medium text-brand hover:underline">{journal.title}</button></td><td className="py-3 pr-3"><Badge tone={display.tone}>{display.label}</Badge></td><td className="py-3 pr-3 text-ink">{instrumentLabel(journal.instrument_id)}</td><td className="py-3 pr-3 text-ink-secondary">{journal.timeframe ?? '—'}</td><td className="numeric py-3 pr-3 text-ink-secondary">{journal.current_plan_revision_id ? `v${journal.version}` : '尚无计划'}</td><td className="numeric py-3 pr-4 text-right text-ink-muted">{formatJournalDate(journal.updated_ts_ms)}</td></tr> })}</tbody>
          </table>
        )}
      </Panel>
    </PageContainer>
  )
}
