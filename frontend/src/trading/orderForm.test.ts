import { describe, expect, test } from 'vitest'
import { toOrderCreateRequest, validateOrderForm, type OrderFormValues } from './orderForm'

const BASE: OrderFormValues = {
  instrument_id: 'okx:SPOT:BTC/USDT',
  side: 'BUY',
  order_type: 'MARKET',
  quantity: '1',
  latency_preset: 'NORMAL',
}

describe('validateOrderForm', () => {
  test('market buy without budget is rejected', () => {
    const issues = validateOrderForm(BASE)
    expect(issues.some((issue) => issue.includes('最大报价预算'))).toBe(true)
  })

  test('market buy with budget passes', () => {
    const issues = validateOrderForm({ ...BASE, max_quote_budget: '105' })
    expect(issues).toEqual([])
  })

  test('limit order without limit price is rejected', () => {
    const issues = validateOrderForm({
      ...BASE,
      order_type: 'LIMIT',
      side: 'SELL',
      limit_price: undefined,
    })
    expect(issues.some((issue) => issue.includes('限价'))).toBe(true)
  })

  test('negative or non-decimal quantity is rejected', () => {
    const issues = validateOrderForm({
      ...BASE,
      side: 'SELL',
      quantity: '-1',
    })
    expect(issues.length).toBeGreaterThan(0)
  })

  test('CUSTOM latency without milliseconds is rejected', () => {
    const issues = validateOrderForm({
      ...BASE,
      side: 'SELL',
      latency_preset: 'CUSTOM',
    })
    expect(issues.some((issue) => issue.includes('CUSTOM'))).toBe(true)
  })

  test('custom_latency_ms with a non-CUSTOM preset is rejected', () => {
    const issues = validateOrderForm({
      ...BASE,
      side: 'SELL',
      custom_latency_ms: 100,
    })
    expect(issues.some((issue) => issue.includes('仅 CUSTOM'))).toBe(true)
  })
})

describe('toOrderCreateRequest', () => {
  test('maps limit order fields', () => {
    const request = toOrderCreateRequest({
      ...BASE,
      order_type: 'LIMIT',
      side: 'SELL',
      limit_price: '102.5',
      latency_preset: 'CUSTOM',
      custom_latency_ms: 250,
    })
    expect(request).toMatchObject({
      side: 'SELL',
      order_type: 'LIMIT',
      limit_price: '102.5',
      latency_preset: 'CUSTOM',
      custom_latency_ms: 250,
    })
    expect('max_quote_budget' in request).toBe(false)
  })
})
