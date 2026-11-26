import Decimal from 'decimal.js'

export interface Level {
  price: string
  quantity: string
}

export interface BookRow {
  price: string
  quantity: string
  /** Cumulative quantity from the best price outward. */
  cumulative: string
  /** 0..1 share of the deepest displayed cumulative quantity (depth bar). */
  depthRatio: number
}

export interface BookView {
  asks: BookRow[] // best ask first (nearest the spread)
  bids: BookRow[] // best bid first
  bestAsk: string | null
  bestBid: string | null
  spread: string | null
  spreadRate: string | null
}

const BOOK_FIXED_HEIGHT_PX = 88
const BOOK_QUALITY_HEIGHT_PX = 25
const BOOK_ROW_HEIGHT_PX = 18

/** Split the available body height evenly between asks and bids. */
export function calculateVisibleDepth(height: number, qualityWarning = false): number {
  const fixedHeight = BOOK_FIXED_HEIGHT_PX + (qualityWarning ? BOOK_QUALITY_HEIGHT_PX : 0)
  return Math.max(3, Math.min(50, Math.floor((height - fixedHeight) / (BOOK_ROW_HEIGHT_PX * 2))))
}

function withCumulative(levels: Level[], descending: boolean, depth: number): BookRow[] {
  const sorted = [...levels].sort((a, b) => {
    const diff = new Decimal(a.price).comparedTo(b.price)
    return descending ? -diff : diff
  })
  const top = sorted.slice(0, depth)
  let running = new Decimal(0)
  const rows = top.map((level) => {
    running = running.plus(level.quantity)
    return { price: level.price, quantity: level.quantity, cumulative: running.toString(), depthRatio: 0 }
  })
  return rows.map((row) => ({
    ...row,
    depthRatio: running.isZero() ? 0 : new Decimal(row.cumulative).div(running).toNumber(),
  }))
}

/**
 * Display model of the real market order book (docs/12 §10.1). Numbers stay
 * Decimal strings; the spread is only derived from a non-crossed best pair.
 */
export function buildBookView(bids: Level[], asks: Level[], depth = 8): BookView {
  const bidRows = withCumulative(bids, true, depth)
  const askRows = withCumulative(asks, false, depth)
  const bestBid = bidRows[0]?.price ?? null
  const bestAsk = askRows[0]?.price ?? null
  let spread: string | null = null
  let spreadRate: string | null = null
  if (bestBid !== null && bestAsk !== null) {
    const value = new Decimal(bestAsk).minus(bestBid)
    if (value.gte(0)) {
      spread = value.toString()
      spreadRate = value.div(bestAsk).times(100).toFixed(4)
    }
  }
  return { asks: askRows, bids: bidRows, bestAsk, bestBid, spread, spreadRate }
}
