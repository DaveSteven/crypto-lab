import Decimal from 'decimal.js'

export function formatTime(tsMs: number | null | undefined): string {
  if (tsMs === null || tsMs === undefined) return '—'
  return new Date(tsMs).toLocaleTimeString('zh-CN', { hour12: false })
}

/**
 * Display form of a decimal string: trailing zeros and exponent notation from
 * database NUMERIC scales are removed ("0.0768000000" → "0.0768", "0E-24" →
 * "0"). Decimal arithmetic only — never converts via float, never rounds.
 */
export function formatDecimal(value: string | null | undefined): string {
  if (value === null || value === undefined) return '—'
  try {
    return new Decimal(value).toFixed()
  } catch {
    return value
  }
}

export interface FinancialFormatOptions {
  minimumFractionDigits?: number
  maximumFractionDigits?: number
  grouping?: boolean
  preserveSmallNonZero?: boolean
}

function addGrouping(value: string): string {
  const [integer, fraction] = value.split('.')
  const sign = integer.startsWith('-') ? '-' : ''
  const digits = sign ? integer.slice(1) : integer
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return `${sign}${grouped}${fraction === undefined ? '' : `.${fraction}`}`
}

/** Display-only Decimal formatter. The source string remains untouched and is exposed in the UI title. */
export function formatFinancial(
  value: string | null | undefined,
  options: FinancialFormatOptions = {},
): string {
  if (value === null || value === undefined) return '—'
  try {
    const decimal = new Decimal(value)
    const minimum = options.minimumFractionDigits ?? 0
    const maximum = Math.max(minimum, options.maximumFractionDigits ?? 2)
    let formatted = decimal.toDecimalPlaces(maximum, Decimal.ROUND_HALF_UP).toFixed(maximum)
    if (options.preserveSmallNonZero && !decimal.isZero() && new Decimal(formatted).isZero()) {
      const threshold = new Decimal(10).pow(-maximum).toFixed(maximum)
      return `${decimal.isNegative() ? '−' : '<'}${threshold}`
    }
    if (maximum > minimum) {
      const [integer, fraction = ''] = formatted.split('.')
      const trimmed = fraction.replace(/0+$/, '')
      const kept = trimmed.padEnd(minimum, '0')
      formatted = kept === '' ? integer : `${integer}.${kept}`
    }
    return options.grouping === false ? formatted : addGrouping(formatted)
  } catch {
    return value
  }
}

export const INSTRUMENT_DISPLAY_RULES: Record<string, { price: number; quantity: number }> = {
  'okx:SPOT:BTC/USDT': { price: 1, quantity: 8 },
  'okx:SPOT:ETH/USDT': { price: 2, quantity: 6 },
}

export function instrumentLabel(instrumentId: string): string {
  return instrumentId.split(':').at(-1) ?? instrumentId
}
