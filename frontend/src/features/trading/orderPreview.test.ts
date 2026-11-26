import { describe, expect, test } from 'vitest'
import { allocate, buildOrderPreview, latencyDisplay } from './orderPreview'
import type { OrderFormValues } from './orderForm'

const base: OrderFormValues = {
  instrument_id: 'okx:SPOT:BTC/USDT',
  side: 'BUY',
  order_type: 'MARKET',
  quantity: '0.1',
  max_quote_budget: '1000',
  latency_preset: 'FAST',
}
const quote = { bid: '99.9', ask: '100.1' }

describe('buildOrderPreview', () => {
  test('market buy references Ask and estimates fee with Decimal precision', () => {
    const preview = buildOrderPreview(base, quote)
    expect(preview.referencePrice).toBe('100.1')
    expect(preview.estimatedNotional).toBe('10.01')
    expect(preview.estimatedFee).toBe('0.01001')
    expect(preview.latencyMs).toBe(50)
    expect(preview.exceedsBudget).toBe(false)
  })

  test('market sell references Bid; limit uses the limit price', () => {
    expect(buildOrderPreview({ ...base, side: 'SELL' }, quote).referencePrice).toBe('99.9')
    expect(
      buildOrderPreview({ ...base, order_type: 'LIMIT', limit_price: '90' }, quote).referencePrice,
    ).toBe('90')
  })

  test('missing quote yields null estimates, never zero', () => {
    const preview = buildOrderPreview(base, {})
    expect(preview.referencePrice).toBeNull()
    expect(preview.estimatedNotional).toBeNull()
  })

  test('flags a budget smaller than estimated notional plus fee', () => {
    expect(buildOrderPreview({ ...base, max_quote_budget: '10' }, quote).exceedsBudget).toBe(true)
  })

  test('custom latency uses the entered milliseconds', () => {
    expect(
      buildOrderPreview({ ...base, latency_preset: 'CUSTOM', custom_latency_ms: 321 }, quote).latencyMs,
    ).toBe(321)
  })
})

describe('allocate', () => {
  const available = { base: '2', quote: '1000' }
  test('sell takes a share of base balance', () => {
    expect(allocate(25, { side: 'SELL', order_type: 'MARKET' }, available, quote)).toEqual({
      quantity: '0.5',
    })
  })

  test('market buy sets budget and a fee-safe quantity rounded down', () => {
    const result = allocate(100, { side: 'BUY', order_type: 'MARKET' }, available, quote)!
    expect(result.max_quote_budget).toBe('1000')
    // 1000 / (100.1 * 1.001) floored to 8 dp, never above budget
    expect(result.quantity).toBe('9.98002996')
  })

  test('limit buy uses the limit price; missing price returns null', () => {
    expect(
      allocate(50, { side: 'BUY', order_type: 'LIMIT', limit_price: '100' }, available, quote)?.quantity,
    ).toBe('4.99500499')
    expect(allocate(50, { side: 'BUY', order_type: 'LIMIT' }, available, quote)).toBeNull()
    expect(allocate(50, { side: 'SELL', order_type: 'MARKET' }, { base: '0', quote: '0' }, quote)).toBeNull()
  })
})

describe('latencyDisplay', () => {
  test('uses user-facing Chinese names and always includes milliseconds', () => {
    expect(latencyDisplay('NORMAL')).toBe('标准（100 ms）')
    expect(latencyDisplay('CUSTOM', 321)).toBe('自定义（321 ms）')
  })
})
