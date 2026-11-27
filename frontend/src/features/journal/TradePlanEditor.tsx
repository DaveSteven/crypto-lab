import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import Decimal from 'decimal.js'
import type { TradingJournal } from '@/shared/api/schemas'
import { RestClient } from '@/shared/api/rest'
import { useSessionStore } from '@/app/sessionStore'
import { formatAmount, formatFee, formatPercentage, formatQuantity } from '@/shared/lib/format'
import { Badge, Button, Input, Label, Panel } from '@/shared/ui'
import { formFromRevision, localPlanPreview, toPlanRequest, type PlannerForm } from './planner'

const rest = new RestClient()

const VALIDATION_LABEL: Record<string, string> = {
  price_relationship: '价格关系',
  price_precision: '价格精度',
  minimum_quantity: '最小数量',
  minimum_notional: '最小金额',
  position_limit: '仓位上限',
  fee_schedule: '手续费配置',
  available_balance: '可用余额',
  account_risk: '账户风险',
  reward_risk: '收益风险比',
  market_data: '行情有效性',
}

export function TradePlanEditor({ journal, onUpdated }: { journal: TradingJournal; onUpdated: () => void }) {
  const session = useSessionStore((state) => state.session)!
  const queryClient = useQueryClient()
  const revisions = journal.plan_revisions ?? []
  const current = revisions.find((item) => item.plan_revision_id === journal.current_plan_revision_id) ?? revisions.at(-1)
  const [form, setForm] = useState<PlannerForm>(() => formFromRevision(current))
  const [revisionReason, setRevisionReason] = useState('保存交易前风险计划')
  const [authoritativeFingerprint, setAuthoritativeFingerprint] = useState<string | null>(null)
  const request = useMemo(() => toPlanRequest(form), [form])
  const fingerprint = request === null ? null : JSON.stringify(request)

  const context = useQuery({
    queryKey: ['planner-context', session.environmentId, session.accountId, journal.instrument_id],
    queryFn: () => rest.plannerContext(session.environmentId, session.accountId, journal.instrument_id),
  })
  const local = localPlanPreview(form, context.data)
  const preview = useMutation({
    mutationFn: () => rest.previewTradePlan(session.environmentId, session.accountId, journal.instrument_id, request!),
    onSuccess: () => setAuthoritativeFingerprint(fingerprint),
  })
  const save = useMutation({
    mutationFn: () => rest.createPlanRevision(
      session.environmentId,
      session.accountId,
      journal.journal_id,
      journal.version,
      revisionReason,
      request!,
    ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['journal', session.environmentId, session.accountId, journal.journal_id] })
      onUpdated()
    },
  })
  const ready = useMutation({
    mutationFn: () => rest.readyJournal(
      session.environmentId,
      session.accountId,
      journal.journal_id,
      journal.version,
      '首次确认风险参数与原始 SL/TP',
    ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['journal', session.environmentId, session.accountId, journal.journal_id] })
      onUpdated()
    },
  })

  const authoritativeCurrent = authoritativeFingerprint !== null && authoritativeFingerprint === fingerprint
  const canSave = request !== null && authoritativeCurrent && preview.data !== undefined && revisionReason.trim() !== ''
  const canReady = journal.status === 'DRAFT' && current?.validation_status === 'PASS'

  function update(key: keyof PlannerForm, value: string) {
    setForm((previous) => ({ ...previous, [key]: value }))
  }

  return (
    <Panel title="Trade Planner" bodyClassName="p-5">
      <div className="mb-4 grid grid-cols-3 gap-3 rounded-[6px] border border-line bg-canvas/40 p-3 text-[12px]">
        <ContextValue label="有效账户资产" value={context.data?.effective_account_equity === null ? '估值不完整' : `${formatAmount(context.data?.effective_account_equity)} ${context.data?.quote_asset ?? ''}`} />
        <ContextValue label="可用余额" value={`${formatAmount(context.data?.available_quote_balance)} ${context.data?.quote_asset ?? ''}`} />
        <ContextValue label="保守手续费率" value={context.data ? `${formatPercentage(new Decimal(context.data.fee_schedule.conservative_fee_rate).mul(100).toString())} %` : '—'} />
        <ContextValue label="行情状态" value={context.data?.market_status === 'VALID' ? '有效' : '不可用'} />
        <ContextValue label="Fee Schedule" value={context.data?.fee_schedule.schedule_id ?? '—'} />
        <ContextValue label="Market Rules" value={context.data?.market_rules.rules_id ?? '—'} />
      </div>

      {context.isError && <p role="alert" className="mb-3 text-[12px] text-negative">无法取得权威 Planner Context，当前计划不能确认。</p>}
      <div className="grid grid-cols-4 gap-3">
        <PlanInput label="计划入场价格" value={form.entryPrice} onChange={(value) => update('entryPrice', value)} unit="USDT" />
        <PlanInput label="计划仓位金额" value={form.positionNotional} onChange={(value) => update('positionNotional', value)} unit="USDT" />
        <PlanInput label="止损价格 SL" value={form.stopLossPrice} onChange={(value) => update('stopLossPrice', value)} unit="USDT" />
        <PlanInput label="止盈价格 TP" value={form.takeProfitPrice} onChange={(value) => update('takeProfitPrice', value)} unit="USDT" />
        <PlanInput label="单笔仓位上限" value={form.maxPositionNotional} onChange={(value) => update('maxPositionNotional', value)} unit="USDT" />
        <PlanInput label="账户风险上限" value={form.maxAccountRiskPercent} onChange={(value) => update('maxAccountRiskPercent', value)} unit="%" />
        <PlanInput label="最低净收益风险比" value={form.minRewardRiskRatio} onChange={(value) => update('minRewardRiskRatio', value)} unit=":1" />
        <Label>Revision 原因<Input className="numeric mt-1" value={revisionReason} onChange={(event) => setRevisionReason(event.target.value)} /></Label>
      </div>

      <div className="mt-4 grid grid-cols-5 gap-3">
        <Metric label="预计买入数量" value={formatQuantity(local?.quantity, journal.instrument_id)} unit={journal.instrument_id.split('/')[0].split(':').at(-1)} />
        <Metric label="预计入场手续费" value={formatFee(local?.entryFee)} unit="USDT" />
        <Metric label="预计退出手续费（TP）" value={formatFee(local?.exitFeeAtTp)} unit="USDT" />
        <Metric label="预计退出手续费（SL）" value={formatFee(local?.exitFeeAtSl)} unit="USDT" />
        <Metric label="预计净盈利" value={formatAmount(local?.netProfit)} unit="USDT" />
        <Metric label="预计净亏损" value={formatAmount(local?.netLoss)} unit="USDT" />
        <Metric label="净收益风险比" value={local?.rewardRisk ?? '—'} unit=":1" />
        <Metric label="账户风险比例" value={formatPercentage(local?.accountRiskPercent)} unit="%" />
        <Metric label="仓位比例" value={formatPercentage(local?.positionPercent)} unit="%" />
        <Metric label="最大允许仓位" value={formatAmount(local?.maximumAllowedNotional)} unit="USDT" />
      </div>

      {preview.data && authoritativeCurrent && (
        <div className="mt-4 rounded-[6px] border border-line p-3">
          <div className="mb-2 flex items-center justify-between"><h3 className="text-[13px] font-medium text-ink">后端权威校验</h3><Badge tone={preview.data.validation_status === 'PASS' ? 'positive' : preview.data.validation_status === 'FAIL' ? 'negative' : 'warning'}>{preview.data.validation_status}</Badge></div>
          <div className="grid grid-cols-2 gap-x-5 gap-y-1">{Object.entries(preview.data.validations).map(([key, item]) => <div key={key} className="flex justify-between text-[12px]" title={item.reason}><span className="text-ink-secondary">{VALIDATION_LABEL[key] ?? key}</span><span className={item.status === 'PASS' ? 'text-positive' : item.status === 'FAIL' ? 'text-negative' : 'text-warning'}>{item.status}</span></div>)}</div>
          <p className="mt-2 text-[11px] text-ink-muted">数值规则通过不代表市场入场信号成立。</p>
        </div>
      )}

      <div className="mt-4 flex items-center justify-end gap-2">
        <Button variant="outline" disabled={request === null || context.data === undefined || preview.isPending} onClick={() => preview.mutate()}>{preview.isPending ? '校验中…' : '执行权威校验'}</Button>
        <Button variant="primary" disabled={!canSave || save.isPending} onClick={() => save.mutate()}>{save.isPending ? '保存中…' : '保存 Plan Revision'}</Button>
        <Button variant="primary" disabled={!canReady || ready.isPending} onClick={() => ready.mutate()}>{ready.isPending ? '确认中…' : '确认计划为 Ready'}</Button>
      </div>
      {(preview.isError || save.isError || ready.isError) && <p role="alert" className="mt-3 text-[12px] text-negative">操作失败：{(preview.error ?? save.error ?? ready.error)?.message}</p>}
      <p className="mt-3 text-[11px] text-warning">所有结果均为计划估算，不是实际收益；止损/止盈仅作记录，不会自动下单或保证亏损上限。</p>
    </Panel>
  )
}

function PlanInput({ label, value, unit, onChange }: { label: string; value: string; unit: string; onChange: (value: string) => void }) { return <Label>{label}<div className="relative mt-1"><Input className="numeric pr-12" aria-label={label} inputMode="decimal" value={value} onChange={(event) => onChange(event.target.value)} /><span className="absolute right-3 top-2 text-[11px] text-ink-muted">{unit}</span></div></Label> }
function ContextValue({ label, value }: { label: string; value: string }) { return <div><div className="text-ink-muted">{label}</div><div className="numeric mt-0.5 truncate text-ink" title={value}>{value}</div></div> }
function Metric({ label, value, unit }: { label: string; value: string; unit?: string }) { return <div className="rounded-[6px] bg-elevated p-3"><div className="text-[11px] text-ink-muted">{label}</div><div className="numeric mt-1 text-[15px] text-ink">{value} {unit && <span className="text-[10px] text-ink-muted">{unit}</span>}</div></div> }
