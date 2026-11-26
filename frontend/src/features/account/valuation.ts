import Decimal from 'decimal.js'
import type { AssetBalance, ExecutionRecord, Position } from '@/shared/api/schemas'

export const VALUATION_CURRENCY = 'USDT'
/** Mirrors the backend's max_book_age_ms: an older book is not an executable bid. */
export const MAX_BID_AGE_MS = 5_000

export interface BidQuote {
  /** Best valid bid (docs/11 §11: Task 1.4 effective-Bid valuation, never Last). */
  price: string
  receivedTsMs: number
}

export interface ValuationInput {
  balances: AssetBalance[]
  positions: Position[]
  executions: ExecutionRecord[]
  /** Lifetime realized PnL per currency from the backend, or null when unavailable/unknown. */
  realizedByCurrency: Record<string, string> | null
  /** Best bid per instrument, only when the market quality is VALID. */
  bids: Record<string, BidQuote | undefined>
  nowMs: number
}

export interface AssetValue {
  asset: string
  total: string
  available: string
  locked: string
  /** Value in USDT, or null when the asset cannot be valued right now. */
  value: string | null
  reason: string | null
  share: string | null // percent of valued total
}

export interface PositionValue {
  instrumentId: string
  quantity: string
  costBasis: string
  marketValue: string | null
  unrealizedPnl: string | null
  realizedPnl: string
}

export interface Valuation {
  currency: string
  totalAssets: string
  /** True when at least one asset is excluded from totalAssets. */
  incomplete: boolean
  available: string
  locked: string
  assets: AssetValue[]
  unvaluable: AssetValue[]
  positions: PositionValue[]
  /** Backend lifetime realized PnL per settlement currency; null = unavailable (never 0). */
  realizedByCurrency: Record<string, string> | null
  unrealizedPnl: string | null
  feesByAsset: { asset: string; amount: string }[]
  valuationTsMs: number | null
}

function dec(value: string | null | undefined): Decimal {
  return new Decimal(value ?? 0)
}

export function computeValuation(input: ValuationInput): Valuation {
  const quoteAvailable = dec(input.balances.find((b) => b.asset === VALUATION_CURRENCY)?.available)
  const quoteLocked = dec(input.balances.find((b) => b.asset === VALUATION_CURRENCY)?.locked)

  let valuationTsMs: number | null = null
  const assets: AssetValue[] = input.balances.map((balance) => {
    const total = dec(balance.available).plus(balance.locked)
    const base: AssetValue = {
      asset: balance.asset,
      total: total.toString(),
      available: balance.available,
      locked: balance.locked,
      value: null,
      reason: null,
      share: null,
    }
    if (balance.asset === VALUATION_CURRENCY) return { ...base, value: total.toString() }
    if (total.isZero()) return { ...base, value: '0' }
    const quote = input.bids[`okx:SPOT:${balance.asset}/${VALUATION_CURRENCY}`]
    if (quote === undefined) {
      return { ...base, reason: '无有效买一价（行情缺失或已失效）' }
    }
    if (input.nowMs - quote.receivedTsMs > MAX_BID_AGE_MS) {
      return { ...base, reason: '买一价已过期' }
    }
    valuationTsMs = Math.max(valuationTsMs ?? 0, quote.receivedTsMs)
    return { ...base, value: total.times(quote.price).toString() }
  })

  const valued = assets.filter((asset) => asset.value !== null)
  const unvaluable = assets.filter((asset) => asset.value === null)
  const totalAssets = valued.reduce((sum, asset) => sum.plus(asset.value ?? 0), new Decimal(0))
  const withShare = assets.map((asset) =>
    asset.value !== null && totalAssets.gt(0)
      ? { ...asset, share: new Decimal(asset.value).div(totalAssets).times(100).toFixed(2) }
      : asset,
  )

  const positions: PositionValue[] = input.positions
    .filter((position) => dec(position.quantity).gt(0))
    .map((position) => {
      const quote = input.bids[position.instrument_id]
      const fresh = quote !== undefined && input.nowMs - quote.receivedTsMs <= MAX_BID_AGE_MS
      const marketValue = fresh ? dec(position.quantity).times(quote.price) : null
      return {
        instrumentId: position.instrument_id,
        quantity: position.quantity,
        costBasis: position.cost_basis,
        marketValue: marketValue?.toString() ?? null,
        unrealizedPnl: marketValue ? marketValue.minus(position.cost_basis).toString() : null,
        realizedPnl: position.realized_pnl,
      }
    })

  const unrealizedPnl = positions.some((p) => p.unrealizedPnl === null)
    ? null
    : positions.reduce((sum, p) => sum.plus(p.unrealizedPnl ?? 0), new Decimal(0)).toString()

  const fees = new Map<string, Decimal>()
  for (const execution of input.executions) {
    fees.set(
      execution.fee_asset,
      (fees.get(execution.fee_asset) ?? new Decimal(0)).plus(execution.fee_amount),
    )
  }

  return {
    currency: VALUATION_CURRENCY,
    totalAssets: totalAssets.toString(),
    incomplete: unvaluable.length > 0,
    available: quoteAvailable.toString(),
    locked: quoteLocked.toString(),
    assets: withShare.filter((asset) => asset.value !== null),
    unvaluable,
    positions,
    realizedByCurrency: input.realizedByCurrency,
    unrealizedPnl,
    feesByAsset: [...fees].map(([asset, amount]) => ({ asset, amount: amount.toString() })),
    valuationTsMs,
  }
}
