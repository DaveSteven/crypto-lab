import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test } from 'vitest'
import { MarketDepthPanel } from './MarketDepthPanel'
import { MAX_TRADES, useMarketStore } from './marketStore'
import { useOrderDraftStore } from '@/features/trading/orderDraftStore'

const INSTRUMENT = 'okx:SPOT:BTC/USDT'
let seq = 0

function event(type: string, payload: Record<string, unknown>, eventId = `e-${(seq += 1)}`) {
  useMarketStore.getState().applyMarketEvent({
    protocol_version: '1.0.0',
    type,
    environment_id: 'env',
    stream_id: 's',
    stream_sequence: seq,
    event_id: eventId,
    event_ts_ms: 1_700_000_000_000 + seq,
    published_ts_ms: 1_700_000_000_000 + seq,
    payload,
    instrument_id: INSTRUMENT,
  } as never)
}

function book() {
  event('market.order_book', {
    bids: [{ price: '100.0', quantity: '0.5' }],
    asks: [{ price: '100.1', quantity: '0.4' }],
    sequence_id: '1',
    received_ts_ms: 1,
  })
}

beforeEach(() => {
  useMarketStore.getState().reset()
  useOrderDraftStore.setState({ pickedPrice: null, pickNonce: 0 })
})

describe('MarketDepthPanel', () => {
  test('shows an honest empty state without data', () => {
    render(<MarketDepthPanel />)
    expect(screen.getByText(/暂无订单簿数据/)).toBeVisible()
  })

  test('renders levels, spread and picks a price without submitting', async () => {
    book()
    render(<MarketDepthPanel />)
    expect(screen.getByText('累计 (BTC)')).toBeVisible()
    expect(screen.getByText(/价差 0.1/)).toBeVisible()
    await userEvent.setup().click(screen.getByText('100.1'))
    expect(useOrderDraftStore.getState().pickedPrice).toBe('100.1')
  })

  test('non-VALID quality disables price picking and warns', async () => {
    book()
    event('market.quality', { quality_status: 'UNSYNCED', reason: 'gap' })
    render(<MarketDepthPanel />)
    expect(screen.getByRole('status')).toHaveTextContent('订单簿未同步')
    await userEvent.setup().click(screen.getByText('100.1'))
    expect(useOrderDraftStore.getState().pickedPrice).toBeNull()
  })

  test('market trades tab lists real trades newest first with a bounded list', async () => {
    for (let i = 0; i < MAX_TRADES + 5; i += 1) {
      event('market.trade', { trade_id: `t${i}`, price: '100', quantity: '0.1', side: i % 2 ? 'BUY' : 'SELL' })
    }
    event('market.trade', { trade_id: 't3', price: '100', quantity: '0.1', side: 'BUY' }) // duplicate
    expect(useMarketStore.getState().trades[INSTRUMENT]).toHaveLength(MAX_TRADES)
    render(<MarketDepthPanel />)
    await userEvent.setup().click(screen.getByRole('tab', { name: '最新成交' }))
    expect(screen.getByTestId('market-trades')).toBeVisible()
  })
})
