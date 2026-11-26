import { cn } from '@/shared/lib/utils'

/**
 * Terminal panel (docs/12 §4.6/§4.7): 4px radius, 36px header, flat
 * surface, no shadows or glassmorphism.
 */
export function Panel({
  title,
  actions,
  children,
  className,
  bodyClassName,
}: {
  title: React.ReactNode
  actions?: React.ReactNode
  children: React.ReactNode
  className?: string
  bodyClassName?: string
}) {
  return (
    <section
      className={cn('flex min-h-0 flex-col overflow-hidden rounded-[6px] border border-line bg-surface', className)}
    >
      <header className="flex h-9 shrink-0 items-center justify-between border-b border-line px-3">
        <h2 className="text-sm font-medium text-ink">{title}</h2>
        {actions !== undefined && <div className="flex items-center gap-1">{actions}</div>}
      </header>
      <div className={cn('min-h-0 flex-1 overflow-auto', bodyClassName)}>{children}</div>
    </section>
  )
}

/** Static learning tooltip (docs/12 §14.4): hover and keyboard focusable. */
export function TermTip({ term, description }: { term: string; description: string }) {
  return (
    <span className="term-tip text-ink-secondary" tabIndex={0} aria-label={`${term}: ${description}`}>
      {term}
      <span role="tooltip" className="term-tip-body">
        {description}
      </span>
    </span>
  )
}

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex min-h-28 items-center justify-center px-5 py-8 text-center">
      <p className="max-w-md text-[13px] text-ink-muted">{message}</p>
    </div>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="px-3 py-4 text-center">
      <p role="alert" className="text-xs text-negative">
        {message}
      </p>
      {onRetry !== undefined && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 rounded-[6px] border border-line px-2 py-1 text-xs text-ink-secondary hover:bg-elevated"
        >
          重试
        </button>
      )}
    </div>
  )
}
