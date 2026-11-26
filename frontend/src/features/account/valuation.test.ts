import { describe, expect, test } from 'vitest'
import { computeValuation, MAX_BID_AGE_MS, type ValuationInput } from './valuation'

const NOW = 100_000
const BTC = 'okx:SPOT:BTC/USDT'

function input(patch: Partial<ValuationInput> = {}): ValuationInput {
  return {
    balances: [
      { asset: 'USDT', available: '9000', locked: '100' },
      { asset: 'BTC', available: '0.5', locked: '0.5' },
    ],
    positions: [
      {
        account_id: 'a',
        instrument_id: BTC,
        base_asset: 'BTC',
        quantity: '1',
        average_cost: '900',
        cost_basis: '900',
        realized_pnl: '5',
        cumulative_fees: '1',
      },
    ],
    executions: [
      { fee_asset: 'USDT', fee_amount: '0.9' },
      { fee_asset: 'USDT', fee_amount: '0.1' },
    ] as never,
    bids: { [BTC]: { price: '1000', receivedTsMs: NOW - 1_000 } },
    nowMs: NOW,
    realizedByCurrency: { USDT: '5' },
    ...patch,
  }
}

describe('computeValuation', () => {
  test('values holdings at the effective Bid in USDT with exact decimals', () => {
    const v = computeValuation(input())
    expect(v.totalAssets).toBe('10100') // 9100 USDT + 1 BTC * 1000
    expect(v.available).toBe('9000')
    expect(v.locked).toBe('100')
    expect(v.incomplete).toBe(false)
    expect(v.positions[0].unrealizedPnl).toBe('100')
    expect(v.unrealizedPnl).toBe('100')
    expect(v.realizedByCurrency).toEqual({ USDT: '5' })
    expect(v.feesByAsset).toEqual([{ asset: 'USDT', amount: '1' }])
    expect(v.assets.map((a) => a.share)).toEqual(['90.10', '9.90'])
  })

  test('missing bid lists the asset as unvaluable and flags the total incomplete', () => {
    const v = computeValuation(input({ bids: {} }))
    expect(v.unvaluable.map((a) => a.asset)).toEqual(['BTC'])
    expect(v.totalAssets).toBe('9100')
    expect(v.incomplete).toBe(true)
    expect(v.positions[0].marketValue).toBeNull()
    expect(v.unrealizedPnl).toBeNull()
  })

  test('an expired bid is never shown as a current valuation', () => {
    const v = computeValuation(
      input({ bids: { [BTC]: { price: '1000', receivedTsMs: NOW - MAX_BID_AGE_MS - 1 } } }),
    )
    expect(v.unvaluable[0].reason).toBe('买一价已过期')
    expect(v.valuationTsMs).toBeNull()
  })

  test('assets with an unknown quote pair are unvaluable, zero balances are not', () => {
    const v = computeValuation(
      input({
        balances: [
          { asset: 'USDT', available: '1', locked: '0' },
          { asset: 'ETH', available: '2', locked: '0' },
          { asset: 'XRP', available: '0', locked: '0' },
        ],
        positions: [],
        executions: [],
      }),
    )
    expect(v.unvaluable.map((a) => a.asset)).toEqual(['ETH'])
    expect(v.assets.map((a) => a.asset)).toEqual(['USDT', 'XRP'])
  })

  test('realized PnL is passed through from the backend and never recomputed from positions', () => {
    // Closed position: no positions left, but the backend lifetime PnL is kept.
    const closed = computeValuation(input({ positions: [], realizedByCurrency: { USDT: '-12.5' } }))
    expect(closed.realizedByCurrency).toEqual({ USDT: '-12.5' })
    expect(computeValuation(input({ realizedByCurrency: null })).realizedByCurrency).toBeNull()
  })

  test('BTC and ETH are valued together with their own bids; frozen amounts count once', () => {
    const ETH = 'okx:SPOT:ETH/USDT'
    const v = computeValuation(
      input({
        balances: [
          { asset: 'USDT', available: '1000', locked: '500' }, // 1500 incl. frozen
          { asset: 'BTC', available: '1', locked: '1' }, // 2 BTC incl. frozen
          { asset: 'ETH', available: '10', locked: '0' },
        ],
        positions: [],
        bids: {
          [BTC]: { price: '1000', receivedTsMs: NOW - 100 },
          [ETH]: { price: '50', receivedTsMs: NOW - 200 },
        },
      }),
    )
    expect(v.totalAssets).toBe('4000') // 1500 + 2*1000 + 10*50
    expect(v.available).toBe('1000')
    expect(v.locked).toBe('500')
    expect(v.incomplete).toBe(false)
    expect(v.assets.map((a) => [a.asset, a.value])).toEqual([
      ['USDT', '1500'],
      ['BTC', '2000'],
      ['ETH', '500'],
    ])
  })

  test('one stale pair makes only that asset unvaluable and flags the total incomplete', () => {
    const ETH = 'okx:SPOT:ETH/USDT'
    const v = computeValuation(
      input({
        balances: [
          { asset: 'USDT', available: '100', locked: '0' },
          { asset: 'BTC', available: '1', locked: '0' },
          { asset: 'ETH', available: '2', locked: '0' },
        ],
        positions: [],
        bids: {
          [BTC]: { price: '1000', receivedTsMs: NOW - 100 },
          [ETH]: { price: '50', receivedTsMs: NOW - MAX_BID_AGE_MS - 1 },
        },
      }),
    )
    expect(v.totalAssets).toBe('1100')
    expect(v.incomplete).toBe(true)
    expect(v.unvaluable.map((a) => a.asset)).toEqual(['ETH'])
  })

  test('records the freshest bid time as the valuation time', () => {
    expect(computeValuation(input()).valuationTsMs).toBe(NOW - 1_000)
  })
})
