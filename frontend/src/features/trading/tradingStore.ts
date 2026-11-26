import { create } from 'zustand'
import Decimal from 'decimal.js'
import type { Snapshot, TradingEvent } from '@/shared/api/schemas'
import type { TradingStateSink } from '@/shared/api/sync'

/** Lifetime realized PnL view kept consistent with the snapshot and positions events. */
export interface PnlView {
  /** UNKNOWN: no snapshot yet (or an older backend without pnl). Never rendered as zero. */
  status: 'AVAILABLE' | 'UNAVAILABLE' | 'UNKNOWN'
  reason?: string
  instruments: Record<string, { quote_asset: string; realized_pnl: string; cumulative_fees: string }>
}

const UNKNOWN_PNL: PnlView = { status: 'UNKNOWN', instruments: {} }

interface TradingState {
  pnl: PnlView
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
  pnl: UNKNOWN_PNL,
  reset: () =>
    set({
      stateVersion: 0,
      balances: [],
      orders: [],
      executions: [],
      positions: [],
      pnl: UNKNOWN_PNL,
    }),
  applySnapshot: (snapshot) =>
    set({
      stateVersion: snapshot.state_version,
      balances: snapshot.balances,
      orders: snapshot.orders,
      executions: snapshot.executions,
      positions: snapshot.positions,
      pnl:
        snapshot.pnl === undefined
          ? UNKNOWN_PNL
          : snapshot.pnl.status === 'AVAILABLE'
            ? {
                status: 'AVAILABLE',
                instruments: Object.fromEntries(
                  (snapshot.pnl.instruments ?? []).map((item) => [
                    item.instrument_id,
                    {
                      quote_asset: item.quote_asset,
                      realized_pnl: item.realized_pnl,
                      cumulative_fees: item.cumulative_fees,
                    },
                  ]),
                ),
              }
            : { status: 'UNAVAILABLE', reason: snapshot.pnl.reason, instruments: {} },
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
          const open = new Decimal(position.quantity).isZero()
            ? positions.filter((item) => item.instrument_id !== position.instrument_id)
            : positions
          // The event carries the cumulative per-instrument PnL even for a fully
          // closed position, so lifetime realized PnL survives the close.
          const quoteAsset = (position as { quote_asset?: string }).quote_asset
          const pnl: PnlView =
            state.pnl.status === 'AVAILABLE' && quoteAsset !== undefined
              ? {
                  ...state.pnl,
                  instruments: {
                    ...state.pnl.instruments,
                    [position.instrument_id]: {
                      quote_asset: quoteAsset,
                      realized_pnl: position.realized_pnl,
                      cumulative_fees: position.cumulative_fees,
                    },
                  },
                }
              : state.pnl
          return { positions: open, pnl, stateVersion: event.state_version ?? state.stateVersion }
        }
        default:
          return state
      }
    }),
}))

/** Lifetime realized PnL per settlement currency; null unless the backend reported AVAILABLE. */
export function realizedPnlByCurrency(pnl: PnlView): Record<string, string> | null {
  if (pnl.status !== 'AVAILABLE') return null
  const totals: Record<string, Decimal> = {}
  for (const item of Object.values(pnl.instruments)) {
    totals[item.quote_asset] = (totals[item.quote_asset] ?? new Decimal(0)).plus(item.realized_pnl)
  }
  return Object.fromEntries(Object.entries(totals).map(([k, v]) => [k, v.toFixed()]))
}
