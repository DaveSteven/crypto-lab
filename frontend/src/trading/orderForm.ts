import { z } from 'zod'
import type { OrderCreateRequest } from '@/api/rest'
import { LatencyPreset } from '@/api/schemas'

const DecimalText = z
  .string()
  .regex(/^\d+(\.\d+)?$/, '必须是正的十进制数字')

export const OrderFormSchema = z
  .object({
    instrument_id: z.string().min(1),
    side: z.enum(['BUY', 'SELL']),
    order_type: z.enum(['MARKET', 'LIMIT']),
    quantity: DecimalText,
    limit_price: DecimalText.optional(),
    max_quote_budget: DecimalText.optional(),
    latency_preset: LatencyPreset,
    custom_latency_ms: z.number().int().min(0).max(60_000).optional(),
  })
  .superRefine((value, ctx) => {
    if (value.order_type === 'LIMIT') {
      if (value.limit_price === undefined || value.limit_price === '') {
        ctx.addIssue({ code: 'custom', message: '限价单必须填写限价', path: ['limit_price'] })
      }
    }
    if (value.order_type === 'MARKET' && value.side === 'BUY') {
      if (value.max_quote_budget === undefined || value.max_quote_budget === '') {
        ctx.addIssue({
          code: 'custom',
          message: '延迟市价买必须显式填写最大报价预算',
          path: ['max_quote_budget'],
        })
      }
    }
    if (value.latency_preset === 'CUSTOM') {
      if (value.custom_latency_ms === undefined) {
        ctx.addIssue({
          code: 'custom',
          message: 'CUSTOM 延迟必须填写自定义毫秒数',
          path: ['custom_latency_ms'],
        })
      }
    } else if (value.custom_latency_ms !== undefined) {
      ctx.addIssue({
        code: 'custom',
        message: '仅 CUSTOM 延迟可填写自定义毫秒数',
        path: ['custom_latency_ms'],
      })
    }
  })

export type OrderFormValues = z.infer<typeof OrderFormSchema>

/** Client-side validation mirrors the backend contract; the backend remains
 * authoritative for every acceptance decision. */
export function validateOrderForm(values: OrderFormValues): string[] {
  const result = OrderFormSchema.safeParse(values)
  if (result.success) return []
  return result.error.issues.map((issue) => `${issue.path.join('.') || '表单'}: ${issue.message}`)
}

export function toOrderCreateRequest(values: OrderFormValues): OrderCreateRequest {
  const request: OrderCreateRequest = {
    account_id: '',
    instrument_id: values.instrument_id,
    side: values.side,
    order_type: values.order_type,
    quantity: values.quantity,
    latency_preset: values.latency_preset,
  }
  if (values.order_type === 'LIMIT' && values.limit_price !== undefined) {
    request.limit_price = values.limit_price
  }
  if (values.max_quote_budget !== undefined) {
    request.max_quote_budget = values.max_quote_budget
  }
  if (values.latency_preset === 'CUSTOM' && values.custom_latency_ms !== undefined) {
    request.custom_latency_ms = values.custom_latency_ms
  }
  return request
}

export const LATENCY_OPTIONS = ['IDEAL', 'FAST', 'NORMAL', 'MEDIUM', 'SLOW', 'HIGH', 'CUSTOM'] as const
