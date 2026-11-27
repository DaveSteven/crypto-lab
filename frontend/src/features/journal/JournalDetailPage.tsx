import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import Decimal from 'decimal.js'
import { useSessionStore } from '@/app/sessionStore'
import { RestClient } from '@/shared/api/rest'
import { formatAmount, formatPercentage, formatPrice, instrumentLabel } from '@/shared/lib/format'
import { Badge, Button, EmptyState, ErrorState, PageContainer, PageHeader, Panel } from '@/shared/ui'
import { formatJournalDate, JOURNAL_STATUS } from './journalDisplay'
import { TradePlanEditor } from './TradePlanEditor'
import { useOrderDraftStore } from '@/features/trading/orderDraftStore'
import { useInstrumentStore } from '@/features/market/instrumentStore'

const rest = new RestClient()

function text(value: string | null | undefined): string {
  return value?.trim() || '尚未记录'
}

export function JournalDetailPage() {
  const navigate = useNavigate()
  const { journalId = '' } = useParams()
  const session = useSessionStore((state) => state.session)!
  const query = useQuery({
    queryKey: ['journal', session.environmentId, session.accountId, journalId],
    queryFn: () => rest.getJournal(session.environmentId, session.accountId, journalId),
    enabled: journalId !== '',
  })

  if (query.isPending) return <PageContainer><EmptyState message="正在加载交易日志…" /></PageContainer>
  if (query.isError) return <PageContainer><PageHeader title="交易日志" actions={<Button variant="outline" onClick={() => navigate('/journal')}>返回列表</Button>} /><ErrorState message="无法读取该交易日志，或它不属于当前账户。" onRetry={() => void query.refetch()} /></PageContainer>
  const journal = query.data
  const status = JOURNAL_STATUS[journal.status]
  const revisions = journal.plan_revisions ?? []
  const current = revisions.find((item) => item.plan_revision_id === journal.current_plan_revision_id) ?? revisions.at(-1)
  const calculation = current?.calculation_json ?? {}
  const confirmed = revisions.find((item) => item.is_initial_confirmed)

  function takeToOrderEntry() {
    const quantity = asString(confirmed?.calculation_json.quantity)
    if (confirmed === undefined || quantity === null) return
    useInstrumentStore.getState().setInstrument(journal.instrument_id)
    useOrderDraftStore.getState().applyPlan({
      instrumentId: journal.instrument_id,
      quantity,
      limitPrice: confirmed.entry_price,
      journalId: journal.journal_id,
    })
    navigate('/trading')
  }

  return (
    <PageContainer>
      <PageHeader title={journal.title} description={`${instrumentLabel(journal.instrument_id)} · ${journal.timeframe ?? '未设置周期'} · 创建于 ${formatJournalDate(journal.created_ts_ms)}`} actions={<><Badge tone={status.tone}>{status.label}</Badge>{confirmed && <Button variant="primary" onClick={takeToOrderEntry}>带入下单草稿</Button>}<Button variant="outline" onClick={() => navigate('/journal')}>返回列表</Button></>} />
      <div className="grid grid-cols-[minmax(0,2fr)_minmax(300px,1fr)] gap-4">
        <div className="space-y-4">
          <Panel title="市场分析" bodyClassName="grid grid-cols-2 gap-5 p-5"><Detail label="市场趋势" value={text(journal.market_trend)} /><Detail label="交易理由" value={text(journal.trade_reason)} /><div className="col-span-2"><Detail label="入场条件" value={text(journal.entry_conditions)} /></div></Panel>
          {journal.status === 'DRAFT' ? <TradePlanEditor journal={journal} onUpdated={() => void query.refetch()} /> : <Panel title="交易计划（只读）" bodyClassName="p-5">
            {current === undefined ? <EmptyState message="尚未保存交易计划。Trade Plan Editor 将在 Task 1.14.4 提供。" /> : <><div className="mb-4 flex items-center justify-between"><span className="text-[12px] text-ink-muted">Revision {current.revision_number} · {formatJournalDate(current.created_ts_ms)}</span><Badge tone={current.validation_status === 'PASS' ? 'positive' : current.validation_status === 'FAIL' ? 'negative' : 'warning'}>{current.validation_status === 'PASS' ? '数值规则通过' : current.validation_status === 'FAIL' ? '数值规则未通过' : '校验不可用'}</Badge></div><div className="grid grid-cols-4 gap-4"><Metric label="计划入场" value={formatPrice(current.entry_price, journal.instrument_id)} unit="USDT" /><Metric label="计划仓位" value={formatAmount(current.planned_position_notional)} unit="USDT" /><Metric label="止损 SL" value={formatPrice(current.stop_loss_price, journal.instrument_id)} unit="USDT" /><Metric label="止盈 TP" value={formatPrice(current.take_profit_price, journal.instrument_id)} unit="USDT" /><Metric label="预计净盈利" value={formatAmount(asString(calculation.estimated_net_profit))} unit="USDT" /><Metric label="预计净亏损" value={formatAmount(asString(calculation.estimated_net_loss))} unit="USDT" /><Metric label="净收益风险比" value={asString(calculation.net_reward_risk_ratio) ?? '—'} /><Metric label="账户风险比例" value={formatPercentage(asPercent(calculation.account_risk_ratio))} unit="%" /></div><p className="mt-4 text-[12px] text-warning">以上均为计划估算，不是实际收益或保证亏损上限；SL/TP 不会自动执行订单。</p></>}
          </Panel>}
          <Panel title="执行与复盘" bodyClassName="grid grid-cols-2 gap-5 p-5"><Detail label="执行备注" value={text(journal.execution_notes)} /><Detail label="复盘总结" value={text(journal.review_summary)} /></Panel>
        </div>
        <div className="space-y-4">
          <Panel title="日志信息" bodyClassName="space-y-3 p-4 text-[13px]"><Row label="状态" value={status.label} /><Row label="主交易品种" value={instrumentLabel(journal.instrument_id)} /><Row label="Journal Version" value={String(journal.version)} /><Row label="最后更新" value={formatJournalDate(journal.updated_ts_ms)} /></Panel>
          <Panel title="计划历史" bodyClassName="p-3">{revisions.length === 0 ? <EmptyState message="暂无 Plan Revision。" /> : <ol className="space-y-2">{[...revisions].reverse().map((revision) => <li key={revision.plan_revision_id} className="rounded-[6px] border border-line p-3"><div className="flex justify-between"><span className="font-medium text-ink">Revision {revision.revision_number}{revision.is_initial_confirmed ? ' · 首次确认快照' : ''}</span><span className="numeric text-[11px] text-ink-muted">{formatJournalDate(revision.created_ts_ms)}</span></div><p className="mt-1 text-[12px] text-ink-secondary">{revision.revision_reason}</p></li>)}</ol>}</Panel>
          <Panel title="关联交易" bodyClassName="p-3"><EmptyState message="Order / Fill 关联将在 Task 1.14.5 实现。本页不会推测或伪造成交结果。" /></Panel>
        </div>
      </div>
    </PageContainer>
  )
}

function asString(value: unknown): string | null { return typeof value === 'string' ? value : null }
function asPercent(value: unknown): string | null { try { return typeof value === 'string' ? new Decimal(value).mul(100).toString() : null } catch { return null } }
function Detail({ label, value }: { label: string; value: string }) { return <div><h3 className="text-[12px] text-ink-muted">{label}</h3><p className="mt-1 whitespace-pre-wrap text-[14px] text-ink">{value}</p></div> }
function Metric({ label, value, unit }: { label: string; value: string; unit?: string }) { return <div className="rounded-[6px] bg-elevated p-3"><div className="text-[12px] text-ink-muted">{label}</div><div className="numeric mt-1 text-[16px] font-medium text-ink" title={value}>{value} {unit && <span className="text-[11px] font-normal text-ink-muted">{unit}</span>}</div></div> }
function Row({ label, value }: { label: string; value: string }) { return <div className="flex justify-between gap-4"><span className="text-ink-muted">{label}</span><span className="text-right text-ink">{value}</span></div> }
