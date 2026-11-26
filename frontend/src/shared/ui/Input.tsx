import type { InputHTMLAttributes, SelectHTMLAttributes } from 'react'
import { cn } from '@/shared/lib/utils'

const controlClass = cn(
  'h-9 w-full rounded-[6px] border border-line bg-transparent px-3 text-sm text-ink',
  'placeholder:text-ink-muted focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-brand',
  'disabled:opacity-50',
)

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(controlClass, className)} {...props} />
}

export function Select({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={cn(controlClass, className)} {...props} />
}

export function Label({
  children,
  htmlFor,
  className,
}: {
  children: React.ReactNode
  htmlFor?: string
  className?: string
}) {
  return (
    <label htmlFor={htmlFor} className={cn('block text-sm text-ink-secondary', className)}>
      {children}
    </label>
  )
}
