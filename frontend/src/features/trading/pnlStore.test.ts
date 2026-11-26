import { beforeEach, describe, expect, test } from 'vitest'
import { realizedPnlByCurrency, useTradingStore } from './tradingStore'
import type { Snapshot, TradingEvent } from '@/shared/api/schemas'

const BTC = 'okx:SPOT/BTC/USDT'

function snapshot(pnl: Snapshot['pnl'], positions: Snapshot['positions'] = []): Snapshot {
  return {
    environment_id: 'e',
    account_id: 'a',
    state_version: 5,
    account: {},
    balances: [],
    orders: [],
    executions: [],
    positions,
    pnl,
  } as unknown as Snapshot
}

function positionEvent(patch: Record<string, unknown>): TradingEvent {
  return {
    type: 'positions',
    state_version: 6,
    payload: {
      instrument_id: BTC,
      quote_asset: 'USDT',
      quantity: '0',
      cost_basis: '0',
      realized_pnl: '9.79',
      cumulative_fees: '0.21',
      ...patch,
    },
  } as unknown as TradingEvent
}

beforeEach(() => useTradingStore.getState().reset())

describe('lifetime realized PnL in the trading store', () => {
  test('is UNKNOWN (rendered "--") until a snapshot arrives, never zero', () => {
    expect(realizedPnlByCurrency(useTradingStore.getState().pnl)).toBeNull()
  })

  test('snapshot AVAILABLE with no fills is an explicit empty (zero) set', () => {
    useTradingStore.getState().applySnapshot(snapshot({ status: 'AVAILABLE', instruments: [] }))
    expect(realizedPnlByCurrency(useTradingStore.getState().pnl)).toEqual({})
  })

  test('UNAVAILABLE from the backend stays unavailable', () => {
    useTradingStore.getState().applySnapshot(snapshot({ status: 'UNAVAILABLE', reason: 'boom' }))
    expect(realizedPnlByCurrency(useTradingStore.getState().pnl)).toBeNull()
    expect(useTradingStore.getState().pnl.reason).toBe('boom')
  })

  test('a closing positions event drops the position but keeps cumulative PnL', () => {
    useTradingStore.getState().applySnapshot(
      snapshot(
        { status: 'AVAILABLE', instruments: [{ instrument_id: BTC, quote_asset: 'USDT', realized_pnl: '0', cumulative_fees: '0.1' }] },
        [{ instrument_id: BTC, quantity: '1' } as never],
      ),
    )
    useTradingStore.getState().applyEvent(positionEvent({ quantity: '0.000000000000000000000000' }))
    const state = useTradingStore.getState()
    expect(state.positions).toEqual([])
    expect(realizedPnlByCurrency(state.pnl)).toEqual({ USDT: '9.79' })
  })

  test('a later snapshot (REST resync) replaces event-derived values consistently', () => {
    useTradingStore.getState().applySnapshot(snapshot({ status: 'AVAILABLE', instruments: [] }))
    useTradingStore.getState().applyEvent(positionEvent({ realized_pnl: '3' }))
    useTradingStore.getState().applySnapshot(
      snapshot({ status: 'AVAILABLE', instruments: [{ instrument_id: BTC, quote_asset: 'USDT', realized_pnl: '3', cumulative_fees: '0' }] }),
    )
    expect(realizedPnlByCurrency(useTradingStore.getState().pnl)).toEqual({ USDT: '3' })
  })

  test('different settlement currencies are kept apart', () => {
    useTradingStore.getState().applySnapshot(
      snapshot({
        status: 'AVAILABLE',
        instruments: [
          { instrument_id: BTC, quote_asset: 'USDT', realized_pnl: '2', cumulative_fees: '0' },
          { instrument_id: 'okx:SPOT/BTC/JPY', quote_asset: 'JPY', realized_pnl: '-300', cumulative_fees: '0' },
          { instrument_id: 'okx:SPOT/ETH/USDT', quote_asset: 'USDT', realized_pnl: '1.5', cumulative_fees: '0' },
        ],
      }),
    )
    expect(realizedPnlByCurrency(useTradingStore.getState().pnl)).toEqual({ JPY: '-300', USDT: '3.5' })
  })
})
