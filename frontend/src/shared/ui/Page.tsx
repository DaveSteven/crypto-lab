import { cn } from '@/shared/lib/utils'

export function PageContainer({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className="h-full overflow-auto">
      <div className={cn('mx-auto w-full max-w-[1440px] px-6 py-6 xl:px-8', className)}>{children}</div>
    </div>
  )
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string
  description?: React.ReactNode
  actions?: React.ReactNode
}) {
  return (
    <header className="mb-5 flex min-h-14 items-start justify-between gap-6">
      <div>
        <h1 className="text-[24px] font-semibold tracking-tight text-ink">{title}</h1>
        {description && <div className="mt-1 text-[13px] text-ink-secondary">{description}</div>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </header>
  )
}
