import { expect, test } from 'vitest'
import { formatDecimal, formatFinancial, instrumentLabel } from './format'

test('formatDecimal trims NUMERIC scale noise without changing the value', () => {
  expect(formatDecimal('0.07683863000000000000')).toBe('0.07683863')
  expect(formatDecimal('0E-24')).toBe('0')
  expect(formatDecimal('61022.600000')).toBe('61022.6')
  expect(formatDecimal('100')).toBe('100')
  expect(formatDecimal(null)).toBe('—')
  expect(formatDecimal('abc')).toBe('abc')
})

test('formatFinancial groups amounts and preserves small non-zero fees', () => {
  expect(formatFinancial('12345.6', { minimumFractionDigits: 2, maximumFractionDigits: 2 })).toBe('12,345.60')
  expect(formatFinancial('0.00000001', { maximumFractionDigits: 2, preserveSmallNonZero: true })).toBe('<0.01')
  expect(formatFinancial('-12.345', { maximumFractionDigits: 2 })).toBe('-12.35')
})

test('instrumentLabel hides the canonical internal prefix', () => {
  expect(instrumentLabel('okx:SPOT:BTC/USDT')).toBe('BTC/USDT')
})
