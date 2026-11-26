import { create } from 'zustand'
import type { Snapshot, TradingEvent } from '@/shared/api/schemas'
import type { TradingStateSink } from '@/shared/api/sync'

interface TradingState {
  stateVersion: number
  balances: Snapshot['balances']
  orders: Snapshot['orders']
  executions: Snapshot['executions']
  positions: Snapshot['positions']
  reset: () => void
}

export type TradingStore = TradingState & TradingStateSink

function upsertById<T extends { order_id?: string; execution_id?: string; asset?: string; instrument_id?: string }>(
  list: T[],
  next: T,
  keyOf: (item: T) => string,
): T[] {
  const key = keyOf(next)
  const index = list.findIndex((item) => keyOf(item) === key)
  if (index === -1) return [...list, next]
  const updated = list.slice()
  updated[index] = next
  return updated
}

/**
 * Authoritative trading view: the REST snapshot replaces everything; WS
 * trading events are applied idempotently per event_id upstream (the sync
 * layer deduplicates before calling the sink).
 */
export const useTradingStore = create<TradingStore>()((set) => ({
  stateVersion: 0,
  balances: [],
  orders: [],
  executions: [],
  positions: [],
  reset: () =>
    set({ stateVersion: 0, balances: [], orders: [], executions: [], positions: [] }),
  applySnapshot: (snapshot) =>
    set({
      stateVersion: snapshot.state_version,
      balances: snapshot.balances,
      orders: snapshot.orders,
      executions: snapshot.executions,
      positions: snapshot.positions,
    }),
  applyEvent: (event: TradingEvent) =>
    set((state) => {
      const payload = event.payload as Record<string, unknown>
      switch (event.type) {
        case 'orders': {
          const order = payload as unknown as Snapshot['orders'][number]
          const orders = upsertById(state.orders, order, (item) => item.order_id)
          return { orders, stateVersion: event.state_version ?? state.stateVersion }
        }
        case 'balances': {
          const balance = payload as unknown as Snapshot['balances'][number]
          const balances = upsertById(state.balances, balance, (item) => item.asset)
          return { balances, stateVersion: event.state_version ?? state.stateVersion }
        }
        case 'executions': {
          const execution = payload as unknown as Snapshot['executions'][number]
          const executions = upsertById(state.executions, execution, (item) => item.execution_id)
          return { executions, stateVersion: event.state_version ?? state.stateVersion }
        }
        case 'positions': {
          const position = payload as unknown as Snapshot['positions'][number]
          const positions = upsertById(state.positions, position, (item) => item.instrument_id)
          // A fully closed position must leave the projection.
          const open = position.quantity === '0' || position.quantity === '0.0'
            ? positions.filter((item) => item.instrument_id !== position.instrument_id)
            : positions
          return { positions: open, stateVersion: event.state_version ?? state.stateVersion }
        }
        default:
          return state
      }
    }),
}))
