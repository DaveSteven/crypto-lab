import { describe, expect, test } from 'vitest'
import { buildBookView } from './orderBook'

describe('buildBookView', () => {
  test('sorts, accumulates decimals exactly and derives the spread', () => {
    const view = buildBookView(
      [{ price: '99.9', quantity: '0.1' }, { price: '100.0', quantity: '0.2' }],
      [{ price: '100.3', quantity: '0.3' }, { price: '100.1', quantity: '0.1' }],
    )
    expect(view.bestBid).toBe('100.0')
    expect(view.bestAsk).toBe('100.1')
    expect(view.spread).toBe('0.1')
    expect(view.bids.map((r) => r.cumulative)).toEqual(['0.2', '0.3'])
    expect(view.asks.map((r) => r.cumulative)).toEqual(['0.1', '0.4'])
    expect(view.asks[1].depthRatio).toBe(1)
  })

  test('crossed or one-sided book yields no spread (never fabricated)', () => {
    expect(buildBookView([{ price: '101', quantity: '1' }], [{ price: '100', quantity: '1' }]).spread).toBeNull()
    expect(buildBookView([], [{ price: '100', quantity: '1' }]).spread).toBeNull()
  })

  test('limits displayed depth', () => {
    const levels = Array.from({ length: 30 }, (_, i) => ({ price: String(100 + i), quantity: '1' }))
    expect(buildBookView([], levels, 12).asks).toHaveLength(12)
  })
})
