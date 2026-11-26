import { useEffect, useRef, type ReactNode } from 'react'

/** Minimal modal dialog: Esc closes, focus moves into the dialog and returns on close. */
export function Dialog({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
}) {
  const ref = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    if (!open) return
    const previous = document.activeElement as HTMLElement | null
    ref.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      previous?.focus?.()
    }
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className="w-[420px] max-w-[92vw] rounded-[8px] border border-line-strong bg-elevated p-4 shadow-xl outline-none"
      >
        <h2 className="mb-3 text-base font-semibold text-ink">{title}</h2>
        {children}
      </div>
    </div>
  )
}
