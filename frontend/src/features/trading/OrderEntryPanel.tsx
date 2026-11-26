import { useEffect, useState, type FormEvent } from 'react'
import Decimal from 'decimal.js'
import { useOrderDraftStore } from './orderDraftStore'
import { ApiError } from '@/shared/api/rest'
import { rest } from '@/shared/api/client'
import { useConnectionStore, connectionDisplay } from '@/app/connectionStore'
import { useMarketStore } from '@/features/market/marketStore'
import { useSessionStore } from '@/app/sessionStore'
import {
  LATENCY_OPTIONS,
  toOrderCreateRequest,
  validateOrderForm,
  type OrderFormValues,
} from './orderForm'
import { useTradingStore } from './tradingStore'
import { splitInstrument, useInstrument } from '@/features/market/instrumentStore'
import {
  ALLOCATION_PERCENTS,
  REFERENCE_FEE_RATE,
  REFERENCE_FEE_SCHEDULE,
  allocate,
  buildOrderPreview,
  latencyDisplay,
  QUANTITY_DECIMALS,
} from './orderPreview'
import { formatDecimal } from '@/shared/lib/format'
import { Button, Dialog, Input, Label, Select, TermTip } from '@/shared/ui'

const EMPTY_FORM: OrderFormValues = {
  instrument_id: '',
  side: 'BUY',
  order_type: 'MARKET',
  quantity: '',
  limit_price: undefined,
  max_quote_budget: undefined,
  latency_preset: 'NORMAL',
  custom_latency_ms: undefined,
}

/** Order Entry (docs/12 §11): order intent only, confirmation dialog and
 * allocation shortcuts arrive with Task 1.12.8. */
export function OrderEntryPanel() {
  const { instrumentId: INSTRUMENT, base: baseAsset, quote: quoteAsset } = useInstrument()
  const session = useSessionStore((state) => state.session)
  const quality = useMarketStore((state) => state.quality[INSTRUMENT])
  const status = useConnectionStore((state) => state.status)
  const display = connectionDisplay(status)

  const [values, setValues] = useState<OrderFormValues>({ ...EMPTY_FORM, instrument_id: INSTRUMENT })
  const [errors, setErrors] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [pending, setPending] = useState<OrderFormValues | null>(null)
  const [inputUnit, setInputUnit] = useState<'base' | 'quote'>('base')
  const balances = useTradingStore((state) => state.balances)
  const ticker = useMarketStore((state) => state.tickers[INSTRUMENT])
  const quote = { bid: ticker?.ticker.bid, ask: ticker?.ticker.ask }
  const availableQuote = balances.find((item) => item.asset === quoteAsset)?.available ?? '0'
  const availableBase = balances.find((item) => item.asset === baseAsset)?.available ?? '0'
  const allocationUnavailable = values.side === 'BUY' && values.order_type === 'MARKET' && !quote.ask

  const marketOk = (quality?.status ?? 'VALID') === 'VALID'
  const connected = display !== 'offline'
  const accountSynced = useTradingStore((state) => state.synced)
  const tradable = marketOk && connected && accountSynced
  const preview = buildOrderPreview(values, quote)

  // A price picked from the order book switches the draft to LIMIT. Subscribing
  // only reacts to picks made after mount (stale picks are ignored).
  useEffect(
    () =>
      useOrderDraftStore.subscribe((state, previous) => {
        if (state.pickNonce === previous.pickNonce || state.pickedPrice === null) return
        const price = state.pickedPrice
        setValues((current) => ({ ...current, order_type: 'LIMIT', limit_price: price }))
      }),
    [],
  )

  function update(patch: Partial<OrderFormValues>) {
    setValues((previous) => ({ ...previous, ...patch }))
  }

  function applyAllocation(percent: number) {
    const result = allocate(percent, values, { base: availableBase, quote: availableQuote }, quote)
    if (result === null) {
      setErrors(['无法按比例计算：缺少可用余额或参考价格。'])
      return
    }
    setErrors([])
    update({ quantity: result.quantity, ...(result.max_quote_budget ? { max_quote_budget: result.max_quote_budget } : {}) })
  }

  function updateQuoteBudget(value: string) {
    const budget = value || undefined
    const ask = quote.ask
    if (budget === undefined || ask == null || !/^\d+(\.\d+)?$/.test(budget)) {
      update({ max_quote_budget: budget, quantity: '' })
      return
    }
    const spendable = new Decimal(budget).div(new Decimal(1).plus(REFERENCE_FEE_RATE))
    const quantity = spendable.div(ask).toDecimalPlaces(QUANTITY_DECIMALS, Decimal.ROUND_DOWN)
    update({ max_quote_budget: budget, quantity: quantity.gt(0) ? quantity.toFixed() : '' })
  }

  /** Step 1 of docs/12 §11.5: client validation, then the confirmation dialog. */
  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (submitting || session === null || !tradable) return
    setMessage(null)
    const issues = validateOrderForm(values)
    if (issues.length > 0) {
      setErrors(issues)
      return
    }
    setErrors([])
    setPending(values)
  }

  /** Step 2: user confirmed — the only path that calls REST. */
  async function confirmSubmit() {
    if (pending === null || submitting || session === null) return
    const submitted = pending
    setSubmitting(true)
    try {
      const request = { ...toOrderCreateRequest(submitted), account_id: session.accountId }
      const order = await rest.createOrder(session.environmentId, request)
      setMessage(
        `订单已提交：${order.order_id.slice(0, 8)}…（状态 ${order.status}）。成交价格与结果由模拟撮合决定。`,
      )
      setValues({
        ...EMPTY_FORM,
        instrument_id: submitted.instrument_id,
        side: submitted.side,
        order_type: submitted.order_type,
        latency_preset: submitted.latency_preset,
      })
    } catch (reason) {
      if (reason instanceof ApiError) {
        setMessage(`下单失败（${reason.code}）：${reason.message}`)
      } else {
        setMessage(`下单失败：${reason instanceof Error ? reason.message : String(reason)}`)
      }
    } finally {
      setSubmitting(false)
      setPending(null)
    }
  }

  return (
    <section
      aria-label="下单"
      className="flex h-full flex-col overflow-hidden rounded-[4px] border border-line bg-surface"
    >
      <header className="flex h-9 shrink-0 items-center justify-between border-b border-line px-3">
        <h2 className="text-sm font-medium text-ink">下单</h2>
        {!marketOk && <Badge text="行情不可用" />}
      </header>

      <form className="flex min-h-0 flex-1 flex-col" onSubmit={handleSubmit} noValidate>
        <div className="min-h-0 flex-1 space-y-3 overflow-auto p-3">
        {!tradable && (
          <p role="alert" className="rounded-[6px] bg-red-50 px-2 py-1.5 text-xs text-red-700">
            {!marketOk
              ? `行情状态异常（${quality?.reason ?? ''}）。`
              : !connected
                ? '连接断开，自动重连中。'
                : '账户状态同步中。'}
            下单已暂停。
          </p>
        )}

        <div className="grid grid-cols-2 gap-2" role="group" aria-label="方向">
          {(['BUY', 'SELL'] as const).map((side) => (
            <button
              key={side}
              type="button"
              onClick={() => update({ side })}
              className={
                values.side === side
                  ? side === 'BUY'
                    ? 'h-9 rounded-[6px] bg-buy font-medium text-white'
                    : 'h-9 rounded-[6px] bg-sell font-medium text-white'
                  : 'h-9 rounded-[6px] border border-line text-sm text-ink-secondary hover:bg-elevated'
              }
            >
              {side === 'BUY' ? '买入' : '卖出'}
            </button>
          ))}
        </div>

        <div className="grid grid-cols-2 gap-2" role="group" aria-label="订单类型">
          {(['MARKET', 'LIMIT'] as const).map((type) => (
            <button
              key={type}
              type="button"
              onClick={() => update({ order_type: type })}
              className={
                values.order_type === type
                  ? 'h-9 rounded-[6px] bg-elevated text-sm font-medium text-ink'
                  : 'h-9 rounded-[6px] border border-line text-sm text-ink-secondary hover:bg-elevated'
              }
            >
              {type === 'MARKET' ? '市价' : '限价'}
            </button>
          ))}
        </div>

        <p className="numeric flex justify-between text-[11px] text-ink-muted" data-testid="available-balance">
          <span>可用余额</span>
          <span>
            {values.side === 'BUY' ? `${formatDecimal(availableQuote)} ${quoteAsset}` : `${formatDecimal(availableBase)} ${baseAsset}`}
          </span>
        </p>

        {values.side === 'BUY' && values.order_type === 'MARKET' && (
          <div className="grid grid-cols-2 gap-1 rounded-[6px] bg-canvas/50 p-1" role="group" aria-label="买入输入单位">
            <button
              type="button"
              onClick={() => setInputUnit('base')}
              className={inputUnit === 'base' ? 'h-7 rounded-[5px] bg-elevated text-[12px] font-medium text-ink' : 'h-7 rounded-[5px] text-[12px] text-ink-secondary hover:bg-elevated/60'}
            >
              按 {baseAsset} 数量
            </button>
            <button
              type="button"
              onClick={() => setInputUnit('quote')}
              className={inputUnit === 'quote' ? 'h-7 rounded-[5px] bg-elevated text-[12px] font-medium text-ink' : 'h-7 rounded-[5px] text-[12px] text-ink-secondary hover:bg-elevated/60'}
            >
              按 {quoteAsset} 金额
            </button>
          </div>
        )}

        {inputUnit === 'base' || values.side !== 'BUY' || values.order_type !== 'MARKET' ? (
          <Label>
            数量（{baseAsset}）
            <Input
              className="mt-1 numeric"
              value={values.quantity}
              onChange={(event) => update({ quantity: event.target.value })}
              inputMode="decimal"
              required
            />
          </Label>
        ) : (
          <Label>
            最大资金预算（{quoteAsset}，含参考手续费）
            <Input
              className="mt-1 numeric"
              value={values.max_quote_budget ?? ''}
              onChange={(event) => updateQuoteBudget(event.target.value)}
              inputMode="decimal"
              required
            />
            <span className="mt-1 block text-[11px] text-ink-muted">
              按参考 Ask 换算数量：<span className="numeric text-ink-secondary">{values.quantity || '—'} {baseAsset}</span>
            </span>
          </Label>
        )}

        <p className="flex flex-wrap gap-x-3 text-[11px] text-ink-muted">
          术语：<TermTip term="限价" description="你愿意成交的价格上限（买）或下限（卖）。限价单可能一直挂着不成交，直到价格到达或你取消。" /> <TermTip term="最大报价预算" description="市价买单最多愿意花费的 USDT，含手续费。预算内部分成交，未成交部分取消，冻结资金释放，不会自动追加资金。" /> <TermTip term="模拟执行延迟" description="从下单到模拟撮合之间的等待时间，用来模拟真实网络与交易所处理耗时；延迟期间行情可能变化。" />
        </p>

        <div className="grid grid-cols-4 gap-1" role="group" aria-label="按可用余额比例">
          {ALLOCATION_PERCENTS.map((percent) => (
            <button
              key={percent}
              type="button"
              disabled={allocationUnavailable}
              onClick={() => applyAllocation(percent)}
              className="h-7 rounded-[6px] border border-line text-xs text-ink-secondary hover:bg-elevated disabled:opacity-50"
            >
              {percent}%
            </button>
          ))}
        </div>

        {values.order_type === 'LIMIT' && (
          <Label>
            限价（{quoteAsset}）
            <Input
              className="mt-1 numeric"
              value={values.limit_price ?? ''}
              onChange={(event) => update({ limit_price: event.target.value || undefined })}
              inputMode="decimal"
            />
          </Label>
        )}

        {values.order_type === 'MARKET' && values.side === 'BUY' && inputUnit === 'base' && (
          <Label>
            最大报价预算（{quoteAsset}，含手续费）
            <Input
              className="mt-1 numeric"
              value={values.max_quote_budget ?? ''}
              onChange={(event) => update({ max_quote_budget: event.target.value || undefined })}
              inputMode="decimal"
            />
          </Label>
        )}

        <Label>
          模拟执行延迟
          <Select
            className="mt-1"
            value={values.latency_preset}
            onChange={(event) =>
              update({ latency_preset: event.target.value as OrderFormValues['latency_preset'] })
            }
          >
            {LATENCY_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {latencyDisplay(option)}
              </option>
            ))}
          </Select>
        </Label>

        {values.latency_preset === 'CUSTOM' && (
          <Label>
            自定义延迟（毫秒）
            <Input
              className="mt-1 numeric"
              value={values.custom_latency_ms ?? ''}
              onChange={(event) =>
                update({
                  custom_latency_ms:
                    event.target.value === '' ? undefined : Number(event.target.value),
                })
              }
              inputMode="numeric"
            />
          </Label>
        )}

        {errors.length > 0 && (
          <ul role="alert" className="list-disc space-y-1 rounded-[6px] bg-red-50 px-2 py-1.5 text-xs text-red-700">
            {errors.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        )}
        {message !== null && (
          <p role="status" className="rounded-[6px] bg-info/10 px-2 py-1.5 text-xs text-info">
            {message}
          </p>
        )}

        <div className="rounded-[6px] border border-line bg-canvas/40 p-2 text-[11px]">
          <div className="flex justify-between text-ink-secondary"><span>{preview.referenceLabel || '参考价'}</span><span className="numeric">{formatDecimal(preview.referencePrice)} {quoteAsset}</span></div>
          <div className="mt-1 flex justify-between text-ink-secondary"><span>参考交易金额</span><span className="numeric">{formatDecimal(preview.estimatedNotional)} {quoteAsset}</span></div>
          <div className="mt-1 flex justify-between text-ink-secondary"><span>参考手续费 <TermTip term="说明" description={`仅使用 ${REFERENCE_FEE_SCHEDULE} 的 ${REFERENCE_FEE_RATE} 做本地参考；真实模拟费用由服务端根据 Maker/Taker 决定。`} /></span><span className="numeric">{formatDecimal(preview.estimatedFee)} {quoteAsset}</span></div>
        </div>

        </div>

        {/* Submit stays pinned: always reachable at the 1280x720 minimum viewport. */}
        <div className="shrink-0 space-y-1 border-t border-line p-3">
        <Button
          variant={values.side === 'BUY' ? 'buy' : 'sell'}
          className="w-full"
          type="submit"
          disabled={submitting || !tradable || session === null}
        >
          {submitting ? '提交中…' : values.side === 'BUY' ? '预览买入订单' : '预览卖出订单'}
        </Button>
        <p className="text-[11px] leading-relaxed text-ink-muted">
          前端只提交订单意图；成交价格、手续费与结果由服务端模拟撮合决定。每次提交使用新的幂等键。
        </p>
        </div>
      </form>

      <Dialog open={pending !== null} title="确认下单" onClose={() => !submitting && setPending(null)}>
        {pending !== null && session !== null && (
          <ConfirmBody values={pending} quote={quote} session={session} />
        )}
        <div className="mt-4 grid grid-cols-2 gap-2">
          <Button variant="outline" onClick={() => setPending(null)} disabled={submitting}>
            返回修改
          </Button>
          <Button
            variant={pending?.side === 'SELL' ? 'sell' : 'buy'}
            onClick={() => void confirmSubmit()}
            disabled={submitting}
          >
            {submitting ? '提交中…' : '确认提交'}
          </Button>
        </div>
      </Dialog>
    </section>
  )
}

function Badge({ text }: { text: string }) {
  return (
    <span className="rounded-full bg-negative/15 px-2 py-0.5 text-xs text-negative">{text}</span>
  )
}

function Line({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 py-0.5 text-xs">
      <dt className="text-ink-muted">{label}</dt>
      <dd className="numeric text-right text-ink">{value}</dd>
    </div>
  )
}

function ConfirmBody({
  values,
  quote,
  session,
}: {
  values: OrderFormValues
  quote: { bid?: string | null; ask?: string | null }
  session: { environmentId: string; accountId: string }
}) {
  const preview = buildOrderPreview(values, quote)
  const { exchange, marketType, base, quote: quoteAsset, symbol } = splitInstrument(values.instrument_id)
  const instrumentLabel = `${exchange.toUpperCase()} · ${symbol} · ${marketType === 'SPOT' ? '现货' : marketType}`
  return (
    <div>
      <dl>
        <Line label="环境" value={`${session.environmentId.slice(0, 16)}…（模拟）`} />
        <Line label="账户" value={`${session.accountId.slice(0, 16)}…`} />
        <Line label="品种" value={`${instrumentLabel}`} />
        <Line label="方向 / 类型" value={`${values.side === 'BUY' ? '买入' : '卖出'} · ${values.order_type === 'MARKET' ? '市价' : '限价 GTC'}`} />
        <Line label="数量" value={`${values.quantity} ${base}`} />
        <Line
          label={preview.referenceLabel || '参考价'}
          value={preview.referencePrice === null ? '--（行情缺失）' : `${preview.referencePrice} ${quoteAsset}`}
        />
        {values.max_quote_budget !== undefined && (
          <Line label="最大资金预算（含手续费）" value={`${values.max_quote_budget} ${quoteAsset}`} />
        )}
        <Line label="预估成交金额" value={preview.estimatedNotional === null ? '--' : `${preview.estimatedNotional} ${quoteAsset}`} />
        <Line label="预估手续费" value={preview.estimatedFee === null ? '--' : `${preview.estimatedFee} ${quoteAsset}`} />
        <Line
          label="模拟执行延迟"
          value={latencyDisplay(values.latency_preset, values.custom_latency_ms)}
        />
      </dl>
      {preview.exceedsBudget && (
        <p role="alert" className="mt-2 rounded-[6px] bg-warning/10 px-2 py-1.5 text-xs text-warning">
          按参考价估算，成交金额加手续费超过预算：预算内部分成交，剩余部分取消。
        </p>
      )}
      <p className="mt-2 text-[11px] leading-relaxed text-ink-muted">
        以上为<strong>本地参考估算</strong>（假设费率 {REFERENCE_FEE_RATE}，参照 {REFERENCE_FEE_SCHEDULE}），不是撮合结果。
        实际成交价、数量与手续费由服务端模拟撮合在延迟后按当时行情决定；订单被接受不等于已成交。
      </p>
    </div>
  )
}
