import Decimal from 'decimal.js'
import type { PaperOrder } from '@/shared/api/schemas'

/** docs/12 §13 logical → Chinese display. The backend enum remains authoritative. */
const STATUS_LABEL: Record<string, string> = {
  PENDING_EXECUTION: '等待执行',
  OPEN: '挂单中',
  PARTIALLY_FILLED: '部分成交',
  FILLED: '全部成交',
  CANCELED: '已取消',
  CANCELLED: '已取消',
  REJECTED: '已拒绝',
}

export const OPEN_STATUSES = new Set(['PENDING_EXECUTION', 'OPEN', 'PARTIALLY_FILLED'])

export function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status
}

/** Quantity still unfilled (never negative). Market buys are budget-bound, so this is the requested remainder. */
export function remainingQuantity(order: Pick<PaperOrder, 'quantity' | 'filled_quantity'>): string {
  const remaining = new Decimal(order.quantity).minus(order.filled_quantity)
  return (remaining.isNegative() ? new Decimal(0) : remaining).toString()
}

/**
 * Extra line for orders that ended after partial fills (docs/12 §13): the
 * cancel/reject status must never hide the quantity that actually executed.
 */
export function fillSummary(order: PaperOrder): string | null {
  const filled = new Decimal(order.filled_quantity)
  if (filled.isZero()) return null
  if (order.status === 'FILLED') return null
  const remaining = remainingQuantity(order)
  if (order.status === 'CANCELED' || order.status === 'REJECTED') {
    return `已成交 ${order.filled_quantity}，取消剩余 ${remaining}`
  }
  return `已成交 ${order.filled_quantity}，剩余 ${remaining}`
}

export type AccountSyncState = 'synced' | 'syncing' | 'stale'

/** Account data freshness shown next to the activity tabs (docs/12 §12). */
export function accountSyncState(display: 'idle' | 'connecting' | 'online' | 'resync' | 'offline'): AccountSyncState {
  if (display === 'online') return 'synced'
  if (display === 'connecting' || display === 'resync') return 'syncing'
  return 'stale'
}

export const SYNC_LABEL: Record<AccountSyncState, string> = {
  synced: '账户已同步',
  syncing: '账户同步中…',
  stale: '连接中断，数据可能过期',
}
