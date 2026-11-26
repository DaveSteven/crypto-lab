import { create } from 'zustand'
import type { WSStatus } from '@/api/ws'

export type ConnectionDisplay = 'idle' | 'connecting' | 'online' | 'resync' | 'offline'

interface ConnectionState {
  status: WSStatus
  streamId: string | null
  /** UTC epoch ms of the last market event received, for freshness display. */
  lastEventTsMs: number | null
  resyncReason: string | null
  update: (patch: Partial<Omit<ConnectionState, 'update' | 'display'>>) => void
}

const DISPLAY_BY_STATUS: Record<WSStatus, ConnectionDisplay> = {
  idle: 'idle',
  connecting: 'connecting',
  ready: 'online',
  subscribed: 'online',
  'resync-required': 'resync',
  closed: 'offline',
}

export const useConnectionStore = create<ConnectionState>()((set) => ({
  status: 'idle',
  streamId: null,
  lastEventTsMs: null,
  resyncReason: null,
  update: (patch) => set(patch),
}))

export function connectionDisplay(status: WSStatus): ConnectionDisplay {
  return DISPLAY_BY_STATUS[status]
}
