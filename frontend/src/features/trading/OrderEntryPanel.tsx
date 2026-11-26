import { useState, type FormEvent } from 'react'
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
import { Button, Input, Label, Select } from '@/shared/ui'

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

/** Order Entry (docs/12 §11): order intent only, confirmation dialog and
 * allocation shortcuts arrive with Task 1.12.8. */
export function OrderEntryPanel() {
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
      setValues({
        ...EMPTY_FORM,
        side: values.side,
        order_type: values.order_type,
        latency_preset: values.latency_preset,
      })
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
    <section
      aria-label="下单"
      className="flex h-full flex-col overflow-auto rounded-[4px] border border-line bg-surface"
    >
      <header className="flex h-9 shrink-0 items-center justify-between border-b border-line px-3">
        <h2 className="text-sm font-medium text-ink">下单</h2>
        {!marketOk && <Badge text="行情不可用" />}
      </header>

      <form className="space-y-3 p-3" onSubmit={handleSubmit} noValidate>
        {!tradable && (
          <p role="alert" className="rounded-[6px] bg-red-50 px-2 py-1.5 text-xs text-red-700">
            {marketOk ? '连接断开，自动重连中。' : `行情状态异常（${quality?.reason ?? ''}）。`}下单已暂停。
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

        <Label>
          数量（BTC）
          <Input
            className="mt-1 numeric"
            value={values.quantity}
            onChange={(event) => update({ quantity: event.target.value })}
            inputMode="decimal"
            required
          />
        </Label>

        {values.order_type === 'LIMIT' && (
          <Label>
            限价（USDT）
            <Input
              className="mt-1 numeric"
              value={values.limit_price ?? ''}
              onChange={(event) => update({ limit_price: event.target.value || undefined })}
              inputMode="decimal"
            />
          </Label>
        )}

        {values.order_type === 'MARKET' && values.side === 'BUY' && (
          <Label>
            最大报价预算（USDT，含手续费）
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
                {option}
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

        <Button
          variant={values.side === 'BUY' ? 'buy' : 'sell'}
          className="w-full"
          type="submit"
          disabled={submitting || !tradable || session === null}
        >
          {submitting ? '提交中…' : values.side === 'BUY' ? '买入提交' : '卖出提交'}
        </Button>
        <p className="text-[11px] leading-relaxed text-ink-muted">
          前端只提交订单意图；成交价格、手续费与结果由服务端模拟撮合决定。每次提交使用新的幂等键。
        </p>
      </form>
    </section>
  )
}

function Badge({ text }: { text: string }) {
  return (
    <span className="rounded-full bg-negative/15 px-2 py-0.5 text-xs text-negative">{text}</span>
  )
}
