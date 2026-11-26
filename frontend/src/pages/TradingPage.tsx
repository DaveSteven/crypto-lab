import { useState, type FormEvent } from 'react'
import { ApiError } from '@/api/rest'
import { rest } from '@/api/client'
import { useConnectionStore, connectionDisplay } from '@/state/connectionStore'
import { useMarketStore } from '@/state/marketStore'
import { useSessionStore } from '@/state/sessionStore'
import {
  LATENCY_OPTIONS,
  toOrderCreateRequest,
  validateOrderForm,
  type OrderFormValues,
} from '@/trading/orderForm'

const INSTRUMENT = 'okx:SPOT:BTC/USDT'

const EMPTY_FORM: OrderFormValues = {
  instrument_id: INSTRUMENT,
  side: 'BUY',
  order_type: 'MARKET',
  quantity: '',
  limit_price: undefined,
  max_quote_budget: undefined,
  latency_preset: 'NORMAL',
  custom_latency_ms: undefined,
}

export function TradingPage() {
  const session = useSessionStore((state) => state.session)
  const quality = useMarketStore((state) => state.quality[INSTRUMENT])
  const status = useConnectionStore((state) => state.status)
  const display = connectionDisplay(status)

  const [values, setValues] = useState<OrderFormValues>(EMPTY_FORM)
  const [errors, setErrors] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const marketOk = (quality?.status ?? 'VALID') === 'VALID'
  const connected = display !== 'offline'
  const tradable = marketOk && connected

  function update(patch: Partial<OrderFormValues>) {
    setValues((previous) => ({ ...previous, ...patch }))
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (submitting || session === null) return
    setMessage(null)
    const issues = validateOrderForm(values)
    if (issues.length > 0) {
      setErrors(issues)
      return
    }
    setErrors([])
    setSubmitting(true)
    try {
      const request = { ...toOrderCreateRequest(values), account_id: session.accountId }
      const order = await rest.createOrder(session.environmentId, request)
      setMessage(
        `订单已提交：${order.order_id.slice(0, 8)}…（状态 ${order.status}）。成交价格与结果由模拟撮合决定。`,
      )
      setValues({ ...EMPTY_FORM, side: values.side, order_type: values.order_type, latency_preset: values.latency_preset })
    } catch (reason) {
      if (reason instanceof ApiError) {
        setMessage(`下单失败（${reason.code}）：${reason.message}`)
      } else {
        setMessage(`下单失败：${reason instanceof Error ? reason.message : String(reason)}`)
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section aria-labelledby="trading-title" className="space-y-4">
      <div className="flex items-center gap-4">
        <h1 id="trading-title" className="text-lg font-semibold">
          模拟交易
        </h1>
        <span className="text-sm text-muted-foreground">{INSTRUMENT}</span>
        {!marketOk && (
          <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs text-red-800">
            行情不可用（{quality?.status ?? '未知'}），暂停下单
          </span>
        )}
      </div>

      {!tradable && (
        <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          {marketOk ? '连接断开，自动重连中。' : `行情状态异常（${quality?.reason ?? ''}）。`}为保护模拟结果，下单已暂停。
        </p>
      )}

      <form className="max-w-xl space-y-3" onSubmit={handleSubmit} noValidate>
        <div className="flex gap-2" role="group" aria-label="方向">
          {(['BUY', 'SELL'] as const).map((side) => (
            <button
              key={side}
              type="button"
              onClick={() => update({ side })}
              className={
                values.side === side
                  ? 'rounded-md bg-accent px-4 py-1.5 text-sm font-medium'
                  : 'rounded-md px-4 py-1.5 text-sm text-muted-foreground hover:bg-accent/50'
              }
            >
              {side === 'BUY' ? '买入' : '卖出'}
            </button>
          ))}
        </div>

        <div className="flex gap-2" role="group" aria-label="订单类型">
          {(['MARKET', 'LIMIT'] as const).map((type) => (
            <button
              key={type}
              type="button"
              onClick={() => update({ order_type: type })}
              className={
                values.order_type === type
                  ? 'rounded-md bg-accent px-4 py-1.5 text-sm font-medium'
                  : 'rounded-md px-4 py-1.5 text-sm text-muted-foreground hover:bg-accent/50'
              }
            >
              {type === 'MARKET' ? '市价' : '限价'}
            </button>
          ))}
        </div>

        <label className="block text-sm">
          数量（BTC）
          <input
            className="mt-1 w-full rounded-md border bg-transparent px-3 py-2 text-sm"
            value={values.quantity}
            onChange={(event) => update({ quantity: event.target.value })}
            inputMode="decimal"
            required
          />
        </label>

        {values.order_type === 'LIMIT' && (
          <label className="block text-sm">
            限价（USDT）
            <input
              className="mt-1 w-full rounded-md border bg-transparent px-3 py-2 text-sm"
              value={values.limit_price ?? ''}
              onChange={(event) => update({ limit_price: event.target.value || undefined })}
              inputMode="decimal"
            />
          </label>
        )}

        {values.order_type === 'MARKET' && values.side === 'BUY' && (
          <label className="block text-sm">
            最大报价预算（USDT，延迟市价买必填）
            <input
              className="mt-1 w-full rounded-md border bg-transparent px-3 py-2 text-sm"
              value={values.max_quote_budget ?? ''}
              onChange={(event) => update({ max_quote_budget: event.target.value || undefined })}
              inputMode="decimal"
            />
          </label>
        )}

        <label className="block text-sm">
          模拟执行延迟
          <select
            className="mt-1 w-full rounded-md border bg-transparent px-3 py-2 text-sm"
            value={values.latency_preset}
            onChange={(event) => update({ latency_preset: event.target.value as OrderFormValues['latency_preset'] })}
          >
            {LATENCY_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>

        {values.latency_preset === 'CUSTOM' && (
          <label className="block text-sm">
            自定义延迟（毫秒）
            <input
              className="mt-1 w-full rounded-md border bg-transparent px-3 py-2 text-sm"
              value={values.custom_latency_ms ?? ''}
              onChange={(event) =>
                update({ custom_latency_ms: event.target.value === '' ? undefined : Number(event.target.value) })
              }
              inputMode="numeric"
            />
          </label>
        )}

        {errors.length > 0 && (
          <ul role="alert" className="list-disc space-y-1 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
            {errors.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        )}
        {message !== null && (
          <p role="status" className="rounded-md bg-sky-50 px-3 py-2 text-sm text-sky-800">
            {message}
          </p>
        )}

        <button
          type="submit"
          disabled={submitting || !tradable || session === null}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
        >
          {submitting ? '提交中…' : '提交订单意图'}
        </button>
        <p className="text-xs text-muted-foreground">
          前端只提交订单意图；成交价格、手续费与成交结果完全由服务端模拟撮合决定。
          每次提交使用新的幂等键，重复点击不会产生重复订单。
        </p>
      </form>
    </section>
  )
}
