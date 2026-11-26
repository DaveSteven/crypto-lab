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
