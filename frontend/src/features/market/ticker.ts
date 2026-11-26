import Decimal from 'decimal.js'

/** 24H change derived from the exchange's own last and open_24h; null if either is missing. */
export function change24h(
  last: string | null | undefined,
  open24h: string | null | undefined,
): { amount: string; percent: string } | null {
  if (last == null || open24h == null) return null
  const open = new Decimal(open24h)
  if (open.lte(0)) return null
  const amount = new Decimal(last).minus(open)
  return { amount: amount.toString(), percent: amount.div(open).times(100).toFixed(2) }
}
