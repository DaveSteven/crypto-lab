export function formatTime(tsMs: number | null | undefined): string {
  if (tsMs === null || tsMs === undefined) return '—'
  return new Date(tsMs).toLocaleTimeString('zh-CN', { hour12: false })
}

/** Display pass-through for decimal strings; never converts via float. */
export function formatDecimal(value: string | null | undefined): string {
  return value ?? '—'
}
