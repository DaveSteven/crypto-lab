import { formatFinancial, INSTRUMENT_DISPLAY_RULES } from '@/shared/lib/format'
import { cn } from '@/shared/lib/utils'

type FinancialKind = 'price' | 'quantity' | 'amount' | 'percent' | 'fee'

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
  const rules = instrumentId === undefined ? undefined : INSTRUMENT_DISPLAY_RULES[instrumentId]
  const options = kind === 'price'
    ? { minimumFractionDigits: rules?.price ?? 0, maximumFractionDigits: rules?.price ?? 8 }
    : kind === 'quantity'
      ? { maximumFractionDigits: rules?.quantity ?? 8 }
      : kind === 'percent'
        ? { minimumFractionDigits: 2, maximumFractionDigits: 4, preserveSmallNonZero: true }
        : kind === 'fee'
          ? { maximumFractionDigits: 8, preserveSmallNonZero: true }
          : { minimumFractionDigits: 2, maximumFractionDigits: 2, preserveSmallNonZero: true }
  return (
    <span className={cn('numeric', className)} title={value == null ? undefined : `完整精度：${value}${unit ? ` ${unit}` : ''}`}>
      {formatFinancial(value, options)}
      {unit && <span className="ml-1 text-[12px] font-normal text-ink-muted">{unit}</span>}
    </span>
  )
}
