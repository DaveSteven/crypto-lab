import { formatAmount, formatFee, formatPercentage, formatPnL, formatPrice, formatQuantity, formatVolume } from '@/shared/lib/format'
import { cn } from '@/shared/lib/utils'

type FinancialKind = 'price' | 'quantity' | 'amount' | 'percent' | 'spreadPercent' | 'fee' | 'pnl' | 'volume'

export function FinancialValue({
  value,
  unit,
  kind = 'amount',
  instrumentId,
  className,
}: {
  value: string | null | undefined
  unit?: string
  kind?: FinancialKind
  instrumentId?: string
  className?: string
}) {
  const formatted = kind === 'price' ? formatPrice(value, instrumentId)
    : kind === 'quantity' ? formatQuantity(value, instrumentId)
      : kind === 'percent' ? formatPercentage(value)
        : kind === 'spreadPercent' ? formatPercentage(value, true)
          : kind === 'fee' ? formatFee(value)
            : kind === 'pnl' ? formatPnL(value)
              : kind === 'volume' ? formatVolume(value)
                : formatAmount(value)
  return (
    <span className={cn('numeric', className)} title={value == null ? undefined : `完整精度：${value}${unit ? ` ${unit}` : ''}`}>
      {formatted}
      {unit && <span className="ml-1 text-[12px] font-normal text-ink-muted">{unit}</span>}
    </span>
  )
}
