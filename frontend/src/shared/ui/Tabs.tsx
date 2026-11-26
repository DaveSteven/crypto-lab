import { cn } from '@/shared/lib/utils'

export interface TabItem<T extends string> {
  value: T
  label: string
}

/** Compact tab strip (docs/12 §10/§12): Order Book / Market Trades and
 * Account Activity tabs. Keyboard accessible via native buttons. */
export function Tabs<T extends string>({
  items,
  value,
  onChange,
  className,
}: {
  items: TabItem<T>[]
  value: T
  onChange: (value: T) => void
  className?: string
}) {
  return (
    <div role="tablist" className={cn('flex items-center gap-0.5', className)}>
      {items.map((item) => (
        <button
          key={item.value}
          type="button"
          role="tab"
          aria-selected={item.value === value}
          onClick={() => onChange(item.value)}
          className={cn(
            'h-7 rounded-[6px] px-2.5 text-xs transition-colors duration-150',
            item.value === value
              ? 'bg-elevated font-medium text-ink'
              : 'text-ink-muted hover:bg-elevated/60 hover:text-ink-secondary',
          )}
        >
          {item.label}
        </button>
      ))}
    </div>
  )
}
