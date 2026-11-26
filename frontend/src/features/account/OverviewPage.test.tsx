import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { OverviewPage } from './OverviewPage'
import { useMarketStore } from '@/features/market/marketStore'
import { useTradingStore } from '@/features/trading/tradingStore'
import type { Snapshot } from '@/shared/api/schemas'

const INSTRUMENT = 'okx:SPOT:BTC/USDT'
const NOW = 1_700_000_000_000

function snapshot(balances: Snapshot['balances']): Snapshot {
  return {
    environment_id: 'e',
    account_id: 'a',
    state_version: 1,
    account: {},
    balances,
    orders: [],
    executions: [],
    positions: [],
  } as unknown as Snapshot
}

function book(receivedTsMs: number) {
  useMarketStore.getState().applyMarketEvent({
    protocol_version: '1.0.0',
    type: 'market.order_book',
    environment_id: 'e',
    stream_id: 's',
    stream_sequence: 1,
    event_id: 'b1',
    event_ts_ms: receivedTsMs,
    published_ts_ms: receivedTsMs,
    payload: {
      bids: [{ price: '1000', quantity: '1' }],
      asks: [{ price: '1001', quantity: '1' }],
      sequence_id: '1',
      received_ts_ms: receivedTsMs,
    },
    instrument_id: INSTRUMENT,
  } as never)
}

function renderPage() {
  return render(
    <MemoryRouter>
      <OverviewPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.spyOn(Date, 'now').mockReturnValue(NOW)
  useMarketStore.getState().reset()
  useTradingStore.getState().reset()
})

describe('OverviewPage', () => {
  test('labels the valuation currency and basis and states that no PnL curve is offered', () => {
    useTradingStore.getState().applySnapshot(snapshot([{ asset: 'USDT', available: '500', locked: '0' }]))
    renderPage()
    expect(screen.getByText(/估值币种 USDT/)).toBeVisible()
    expect(screen.getByText(/不使用最新成交价/)).toBeVisible()
    expect(screen.getByTestId('total-assets')).toHaveTextContent('500 USDT')
    expect(screen.getByText(/暂不提供收益曲线/)).toBeVisible()
  })

  test('values BTC at the valid bid and shows the data time', () => {
    useTradingStore
      .getState()
      .applySnapshot(snapshot([{ asset: 'USDT', available: '100', locked: '0' }, { asset: 'BTC', available: '2', locked: '0' }]))
    book(NOW - 500)
    renderPage()
    expect(screen.getByTestId('total-assets')).toHaveTextContent('2100 USDT')
    expect(screen.queryByTestId('valuation-incomplete')).toBeNull()
  })

  test('without a valid bid the BTC is listed as unvaluable and the total is flagged incomplete', () => {
    useTradingStore
      .getState()
      .applySnapshot(snapshot([{ asset: 'USDT', available: '100', locked: '0' }, { asset: 'BTC', available: '2', locked: '0' }]))
    renderPage()
    expect(screen.getByTestId('valuation-incomplete')).toHaveTextContent('1 项无法估值')
    expect(screen.getByTestId('unvaluable')).toHaveTextContent('BTC 2')
    expect(screen.getByTestId('total-assets')).toHaveTextContent('100 USDT')
    expect(screen.getByText('总资产（不完整）')).toBeVisible()
  })

  test('a bid from a non-VALID market is not used for valuation', () => {
    useTradingStore
      .getState()
      .applySnapshot(snapshot([{ asset: 'BTC', available: '1', locked: '0' }]))
    book(NOW - 100)
    useMarketStore.getState().applyMarketEvent({
      protocol_version: '1.0.0',
      type: 'market.quality',
      environment_id: 'e',
      stream_id: 's',
      stream_sequence: 2,
      event_id: 'q',
      event_ts_ms: NOW,
      published_ts_ms: NOW,
      payload: { quality_status: 'STALE', reason: 'stale' },
      instrument_id: INSTRUMENT,
    } as never)
    renderPage()
    expect(screen.getByTestId('unvaluable')).toBeVisible()
  })
})
