import type { BadgeProps } from '@/shared/ui'
import type { JournalStatus } from '@/shared/api/schemas'

export const JOURNAL_STATUS: Record<JournalStatus, { label: string; tone: BadgeProps['tone'] }> = {
  DRAFT: { label: '草稿', tone: 'neutral' },
  READY: { label: '已确认计划', tone: 'brand' },
  ACTIVE: { label: '进行中', tone: 'info' },
  CLOSED: { label: '交易已完成', tone: 'positive' },
  REVIEWED: { label: '已复盘', tone: 'positive' },
  CANCELLED: { label: '已取消', tone: 'negative' },
}

export function formatJournalDate(tsMs: number): string {
  return new Date(tsMs).toLocaleString('zh-CN', { hour12: false })
}
