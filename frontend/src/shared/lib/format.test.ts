import { expect, test } from 'vitest'
import { formatAmount, formatDecimal, formatFee, formatFinancial, formatLatency, formatPercentage, formatPnL, formatPrice, formatQuantity, formatVolume, instrumentLabel } from './format'

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

test('financial formatters follow the global display rules without mutating input precision', () => {
  expect(formatAmount('12345.6789')).toBe('12,345.68')
  expect(formatPrice('60700', 'okx:SPOT:BTC/USDT')).toBe('60,700.0')
  expect(formatQuantity('0.123456789')).toBe('0.123457')
  expect(formatQuantity('0.0000001')).toBe('<0.000001')
  expect(formatPercentage('1.234')).toBe('1.23')
  expect(formatPercentage('0.00002', true)).toBe('0.00002')
  expect(formatVolume('1234.567')).toBe('1,234.57')
  expect(formatFee('0.00000001')).toBe('0.00000001')
  expect(formatPnL('12.3')).toBe('+12.30')
  expect(formatPnL('0')).toBe('0.00')
  expect(formatLatency('99.6')).toBe('100 ms')
})
