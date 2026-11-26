import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { OverviewPage } from './OverviewPage'
import { useMarketStore } from '@/features/market/marketStore'
import { useTradingStore } from '@/features/trading/tradingStore'
import type { Snapshot } from '@/shared/api/schemas'

const INSTRUMENT = 'okx:SPOT:BTC/USDT'
const NOW = 1_700_000_000_000

function snapshot(balances: Snapshot['balances'], pnl?: Snapshot['pnl']): Snapshot {
  return {
    environment_id: 'e',
    account_id: 'a',
    state_version: 1,
    account: {},
    balances,
    orders: [],
    executions: [],
    positions: [],
    pnl,
  } as unknown as Snapshot
}

const pnlOf = (instruments: Array<[string, string, string]>): Snapshot['pnl'] => ({
  status: 'AVAILABLE',
  instruments: instruments.map(([instrument_id, quote_asset, realized_pnl]) => ({
    instrument_id,
    quote_asset,
    realized_pnl,
    cumulative_fees: '0',
  })),
})

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
    expect(screen.getByTestId('total-assets')).toHaveTextContent(/500\.00\s*USDT/)
    expect(screen.getByText(/暂不提供收益曲线/)).toBeVisible()
  })

  test('values BTC at the valid bid and shows the data time', () => {
    useTradingStore
      .getState()
      .applySnapshot(snapshot([{ asset: 'USDT', available: '100', locked: '0' }, { asset: 'BTC', available: '2', locked: '0' }]))
    book(NOW - 500)
    renderPage()
    expect(screen.getByTestId('total-assets')).toHaveTextContent(/2,100\.00\s*USDT/)
    expect(screen.queryByTestId('valuation-incomplete')).toBeNull()
  })

  test('without a valid bid the BTC is listed as unvaluable and the total is flagged incomplete', () => {
    useTradingStore
      .getState()
      .applySnapshot(snapshot([{ asset: 'USDT', available: '100', locked: '0' }, { asset: 'BTC', available: '2', locked: '0' }]))
    renderPage()
    expect(screen.getByTestId('valuation-incomplete')).toHaveTextContent('1 项资产暂时无法估值')
    expect(screen.getByTestId('unvaluable')).toHaveTextContent('BTC 2')
    expect(screen.getByTestId('total-assets')).toHaveTextContent(/100\.00\s*USDT/)
    expect(screen.getByText('总资产（估值不完整）')).toBeVisible()
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

  test('closed position still shows the lifetime realized PnL from the backend', () => {
    useTradingStore
      .getState()
      .applySnapshot(
        snapshot([{ asset: 'USDT', available: '10009.79', locked: '0' }], pnlOf([[INSTRUMENT, 'USDT', '9.79']])),
      )
    renderPage()
    expect(screen.getByTestId('realized-pnl')).toHaveTextContent(/9\.79\s*USDT/)
  })

  test('a new account shows a legitimate zero, a loss shows a negative number', () => {
    useTradingStore.getState().applySnapshot(snapshot([{ asset: 'USDT', available: '10000', locked: '0' }], pnlOf([])))
    const view = renderPage()
    expect(screen.getByTestId('realized-pnl')).toHaveTextContent(/0\.00\s*USDT/)
    view.unmount()
    useTradingStore
      .getState()
      .applySnapshot(snapshot([{ asset: 'USDT', available: '9990', locked: '0' }], pnlOf([[INSTRUMENT, 'USDT', '-10.19']])))
    renderPage()
    expect(screen.getByTestId('realized-pnl')).toHaveTextContent(/-10\.19\s*USDT/)
  })

  test('currencies are shown separately and unavailable PnL is "--" not 0', () => {
    useTradingStore.getState().applySnapshot(
      snapshot(
        [{ asset: 'USDT', available: '1', locked: '0' }],
        pnlOf([
          [INSTRUMENT, 'USDT', '4'],
          ['okx:SPOT:BTC/JPY', 'JPY', '-1000'],
        ]),
      ),
    )
    const view = renderPage()
    expect(screen.getByTestId('realized-pnl')).toHaveTextContent(/4\.00\s*USDT·-1,000\.00\s*JPY/)
    view.unmount()
    useTradingStore.getState().applySnapshot(
      snapshot([{ asset: 'USDT', available: '1', locked: '0' }], { status: 'UNAVAILABLE', reason: 'x' }),
    )
    renderPage()
    expect(screen.getByTestId('realized-pnl')).toHaveTextContent('—')
  })

  test('BTC and ETH held together are both valued from their own valid bids', () => {
    useTradingStore.getState().applySnapshot(
      snapshot(
        [
          { asset: 'USDT', available: '100', locked: '50' },
          { asset: 'BTC', available: '1', locked: '0' },
          { asset: 'ETH', available: '10', locked: '0' },
        ],
        pnlOf([]),
      ),
    )
    book(NOW - 100)
    useMarketStore.getState().applyMarketEvent({
      protocol_version: '1.0.0',
      type: 'market.order_book',
      environment_id: 'e',
      stream_id: 's',
      stream_sequence: 3,
      event_id: 'b-eth',
      event_ts_ms: NOW - 100,
      published_ts_ms: NOW - 100,
      payload: {
        bids: [{ price: '50', quantity: '9' }],
        asks: [{ price: '51', quantity: '9' }],
        sequence_id: '2',
        received_ts_ms: NOW - 100,
      },
      instrument_id: 'okx:SPOT:ETH/USDT',
    } as never)
    renderPage()
    expect(screen.getByTestId('total-assets')).toHaveTextContent(/1,650\.00\s*USDT/) // 150 + 1000 + 500
    expect(screen.queryByTestId('valuation-incomplete')).toBeNull()
  })
})
