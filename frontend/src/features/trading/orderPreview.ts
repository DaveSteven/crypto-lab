import Decimal from 'decimal.js'
import type { OrderFormValues } from './orderForm'

/**
 * Reference fee rate for LOCAL ESTIMATES ONLY. It mirrors the backend's
 * `phase1-default-v1` schedule (maker/taker 0.1%) but is not read from the
 * backend; the real fee is decided by the simulated matching engine.
 */
export const REFERENCE_FEE_RATE = '0.001'
export const REFERENCE_FEE_SCHEDULE = 'phase1-default-v1'
export const QUANTITY_DECIMALS = 8
export const QUOTE_DECIMALS = 8

export const PRESET_LATENCY_MS: Record<string, number> = {
  IDEAL: 0,
  FAST: 50,
  NORMAL: 100,
  MEDIUM: 250,
  SLOW: 500,
  HIGH: 1_000,
}

export interface QuoteContext {
  bid?: string | null
  ask?: string | null
}

export interface OrderPreview {
  referencePrice: string | null
  referenceLabel: string
  estimatedNotional: string | null
  estimatedFee: string | null
  /** Market buy: estimated notional + fee exceeds the stated budget. */
  exceedsBudget: boolean
  latencyMs: number | null
}

function isPositive(value: string | undefined | null): value is string {
  if (value == null || !/^\d+(\.\d+)?$/.test(value)) return false
  return new Decimal(value).gt(0)
}

/** Local reference estimate (docs/12 §11.4) — never an actual match result. */
export function buildOrderPreview(values: OrderFormValues, quote: QuoteContext): OrderPreview {
  let referencePrice: string | null = null
  let referenceLabel = ''
  if (values.order_type === 'LIMIT') {
    referencePrice = isPositive(values.limit_price) ? values.limit_price : null
    referenceLabel = '限价'
  } else if (values.side === 'BUY') {
    referencePrice = isPositive(quote.ask) ? quote.ask : null
    referenceLabel = '参考卖一价（Ask）'
  } else {
    referencePrice = isPositive(quote.bid) ? quote.bid : null
    referenceLabel = '参考买一价（Bid）'
  }

  let estimatedNotional: string | null = null
  let estimatedFee: string | null = null
  let exceedsBudget = false
  if (referencePrice !== null && isPositive(values.quantity)) {
    const notional = new Decimal(values.quantity).times(referencePrice)
    const fee = notional.times(REFERENCE_FEE_RATE)
    estimatedNotional = notional.toString()
    estimatedFee = fee.toString()
    if (values.order_type === 'MARKET' && values.side === 'BUY' && isPositive(values.max_quote_budget)) {
      exceedsBudget = notional.plus(fee).gt(values.max_quote_budget)
    }
  }

  const latencyMs =
    values.latency_preset === 'CUSTOM'
      ? (values.custom_latency_ms ?? null)
      : (PRESET_LATENCY_MS[values.latency_preset] ?? null)

  return { referencePrice, referenceLabel, estimatedNotional, estimatedFee, exceedsBudget, latencyMs }
}

export const ALLOCATION_PERCENTS = [25, 50, 75, 100] as const

export interface AllocationResult {
  quantity: string
  max_quote_budget?: string
}

/**
 * Allocation shortcut. Decimal math, rounded DOWN so the result never needs
 * more funds than available. Returns null when inputs are insufficient.
 */
export function allocate(
  percent: number,
  values: Pick<OrderFormValues, 'side' | 'order_type' | 'limit_price'>,
  available: { base: string; quote: string },
  quote: QuoteContext,
): AllocationResult | null {
  const ratio = new Decimal(percent).div(100)
  if (values.side === 'SELL') {
    const quantity = new Decimal(available.base).times(ratio).toDecimalPlaces(QUANTITY_DECIMALS, Decimal.ROUND_DOWN)
    return quantity.gt(0) ? { quantity: quantity.toFixed() } : null
  }
  const price = values.order_type === 'LIMIT' ? values.limit_price : quote.ask
  if (!isPositive(price)) return null
  const budget = new Decimal(available.quote).times(ratio).toDecimalPlaces(QUOTE_DECIMALS, Decimal.ROUND_DOWN)
  const quantity = budget
    .div(new Decimal(price).times(new Decimal(1).plus(REFERENCE_FEE_RATE)))
    .toDecimalPlaces(QUANTITY_DECIMALS, Decimal.ROUND_DOWN)
  if (!quantity.gt(0)) return null
  return values.order_type === 'MARKET'
    ? { quantity: quantity.toFixed(), max_quote_budget: budget.toFixed() }
    : { quantity: quantity.toFixed() }
}
