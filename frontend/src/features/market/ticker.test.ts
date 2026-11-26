import { expect, test } from 'vitest'
import { change24h } from './ticker'

test('derives 24H change from exchange fields only', () => {
  expect(change24h('101', '100')).toEqual({ amount: '1', percent: '1.00' })
  expect(change24h('99', '100')?.percent).toBe('-1.00')
  expect(change24h(null, '100')).toBeNull()
  expect(change24h('101', undefined)).toBeNull()
  expect(change24h('101', '0')).toBeNull()
})
