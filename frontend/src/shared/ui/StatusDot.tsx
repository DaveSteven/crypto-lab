import { cn } from '@/shared/lib/utils'

export type DotTone = 'positive' | 'negative' | 'warning' | 'info' | 'neutral'

const DOT_CLASS: Record<DotTone, string> = {
  positive: 'bg-positive',
  negative: 'bg-negative',
  warning: 'bg-warning',
  info: 'bg-info',
  neutral: 'bg-neutral',
}

/** Status indicator: never color-only (docs/12 §4.2) — pair with text. */
export function StatusDot({ tone, label }: { tone: DotTone; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={cn('h-1.5 w-1.5 rounded-full', DOT_CLASS[tone])} aria-hidden />
      <span>{label}</span>
    </span>
  )
}
