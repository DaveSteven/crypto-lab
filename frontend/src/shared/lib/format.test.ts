import { expect, test } from 'vitest'
import { formatDecimal } from './format'

test('formatDecimal trims NUMERIC scale noise without changing the value', () => {
  expect(formatDecimal('0.07683863000000000000')).toBe('0.07683863')
  expect(formatDecimal('0E-24')).toBe('0')
  expect(formatDecimal('61022.600000')).toBe('61022.6')
  expect(formatDecimal('100')).toBe('100')
  expect(formatDecimal(null)).toBe('—')
  expect(formatDecimal('abc')).toBe('abc')
})
