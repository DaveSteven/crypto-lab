import { cva, type VariantProps } from 'class-variance-authority'
import type { ButtonHTMLAttributes } from 'react'
import { cn } from '@/shared/lib/utils'

const buttonVariants = cva(
  // docs/12 §4.6/§4.7: radius 6px, height 36px (compact 28px), 100-180ms transitions.
  cn(
    'inline-flex items-center justify-center gap-2 rounded-[6px] text-sm font-medium',
    'transition-colors duration-150 disabled:pointer-events-none disabled:opacity-50',
    'focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-brand',
  ),
  {
    variants: {
      variant: {
        // Brand teal: selection / primary actions only (docs/12 §4.1).
        primary: 'bg-brand text-canvas hover:bg-brand-hover',
        buy: 'bg-buy text-white hover:opacity-90',
        sell: 'bg-sell text-white hover:opacity-90',
        secondary: 'bg-elevated text-ink hover:bg-line/60',
        outline: 'border border-line text-ink hover:bg-elevated',
        ghost: 'text-ink-secondary hover:bg-elevated hover:text-ink',
      },
      size: {
        default: 'h-9 px-4',
        compact: 'h-7 px-2.5 text-xs',
        icon: 'h-7 w-7',
      },
    },
    defaultVariants: { variant: 'secondary', size: 'default' },
  },
)

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

export function Button({ className, variant, size, ...props }: ButtonProps) {
  return <button className={cn(buttonVariants({ variant, size }), className)} {...props} />
}
