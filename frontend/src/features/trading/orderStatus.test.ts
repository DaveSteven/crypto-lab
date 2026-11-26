import { describe, expect, test } from 'vitest'
import { accountSyncState, fillSummary, remainingQuantity, statusLabel } from './orderStatus'
import type { PaperOrder } from '@/shared/api/schemas'

const order = (patch: Partial<PaperOrder>) =>
  ({ quantity: '1', filled_quantity: '0', status: 'OPEN', ...patch }) as PaperOrder

describe('order status presentation', () => {
  test('maps every backend status to Chinese and passes unknown through', () => {
    expect(['PENDING_EXECUTION', 'OPEN', 'PARTIALLY_FILLED', 'FILLED', 'CANCELED', 'REJECTED'].map(statusLabel)).toEqual(
      ['等待执行', '挂单中', '部分成交', '全部成交', '已取消', '已拒绝'],
    )
    expect(statusLabel('NEW_STATE')).toBe('NEW_STATE')
  })

  test('canceled after a partial fill keeps the executed quantity visible', () => {
    const summary = fillSummary(order({ status: 'CANCELED', filled_quantity: '0.4' }))
    expect(summary).toBe('已成交 0.4，取消剩余 0.6')
    expect(fillSummary(order({ status: 'CANCELED' }))).toBeNull()
    expect(fillSummary(order({ status: 'FILLED', filled_quantity: '1' }))).toBeNull()
    expect(fillSummary(order({ status: 'PARTIALLY_FILLED', filled_quantity: '0.1' }))).toBe('已成交 0.1，剩余 0.9')
  })

  test('remaining quantity is exact and never negative', () => {
    expect(remainingQuantity(order({ quantity: '0.3', filled_quantity: '0.1' }))).toBe('0.2')
    expect(remainingQuantity(order({ quantity: '1', filled_quantity: '1.5' }))).toBe('0')
  })

  test('account sync tri-state from connection display', () => {
    expect(accountSyncState('online')).toBe('synced')
    expect(accountSyncState('resync')).toBe('syncing')
    expect(accountSyncState('connecting')).toBe('syncing')
    expect(accountSyncState('offline')).toBe('stale')
  })
})
