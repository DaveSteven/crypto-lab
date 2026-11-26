import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'

const candleHistory = vi.fn()

vi.mock('@/api/client', () => ({
  rest: { candleHistory: (...args: unknown[]) => candleHistory(...args) },
}))

const chartApi = {
  addSeries: vi.fn(() => ({
    setData: vi.fn(),
    update: vi.fn(),
  })),
  remove: vi.fn(),
  timeScale: vi.fn(() => ({ fitContent: vi.fn() })),
  applyOptions: vi.fn(),
}

vi.mock('lightweight-charts', () => ({
  CandlestickSeries: {},
  createChart: vi.fn(() => chartApi),
}))

import { MarketPage, INSTRUMENT } from './MarketPage'
import { useMarketStore } from '@/state/marketStore'
import { useConnectionStore } from '@/state/connectionStore'

function historyResponse(count: number) {
  return {
    source: 'OKX_PUBLIC_REST',
    items: Array.from({ length: count }, (_, index) => ({
      event_id: `h-${index}`,
      event_type: 'CANDLE',
      instrument_id: INSTRUMENT,
      received_ts_ms: 1_000,
      quality_status: 'VALID',
      payload: {
        interval: '1m',
        open_ts_ms: (index + 1) * 60_000,
        close_ts_ms: (index + 2) * 60_000,
        open: '100',
        high: '102',
        low: '99',
        close: '101',
        is_closed: true,
      },
    })),
  }
}

beforeEach(() => {
  candleHistory.mockReset().mockResolvedValue(historyResponse(3))
  useMarketStore.getState().reset()
  useConnectionStore.getState().update({ status: 'subscribed', resyncReason: null })
})

describe('MarketPage', () => {
  test('loads history, renders ticker and chart container', async () => {
    useMarketStore.getState().applyMarketEvent({
      protocol_version: '1.0.0',
      type: 'market.ticker',
      environment_id: 'env-1',
      stream_id: 's',
      stream_sequence: 1,
      event_id: 't-1',
      event_ts_ms: 1_100,
      published_ts_ms: 1_100,
      payload: { bid: '100.9', ask: '101.1', last: '101' },
      instrument_id: INSTRUMENT,
    })
    render(<MarketPage />)
    expect(await screen.findByText('BTC/USDT')).toBeVisible()
    expect(screen.getByTestId('candle-chart')).toBeVisible()
    expect(screen.getByText(/来源：OKX 公共行情/)).toBeVisible()
    await waitFor(() => expect(candleHistory).toHaveBeenCalledWith(INSTRUMENT, '1m', { limit: 200 }))
    expect(useMarketStore.getState().candles[`${INSTRUMENT}|1m`]).toHaveLength(3)
  })

  test('switching interval fetches that interval history', async () => {
    const user = userEvent.setup()
    render(<MarketPage />)
    await waitFor(() => expect(candleHistory).toHaveBeenCalledTimes(1))
    await user.click(screen.getByRole('button', { name: '5m' }))
    await waitFor(() => expect(candleHistory).toHaveBeenCalledWith(INSTRUMENT, '5m', { limit: 200 }))
  })

  test('load-earlier paginates with the earliest open time as cursor', async () => {
    const user = userEvent.setup()
    render(<MarketPage />)
    await waitFor(() => expect(useMarketStore.getState().candles[`${INSTRUMENT}|1m`]).toHaveLength(3))
    await user.click(screen.getByRole('button', { name: '加载更早' }))
    await waitFor(() =>
      expect(candleHistory).toHaveBeenCalledWith(INSTRUMENT, '1m', {
        limit: 200,
        before: 60_000,
      }),
    )
  })

  test('non-VALID quality shows a blocking alert', () => {
    useMarketStore.getState().applyMarketEvent({
      protocol_version: '1.0.0',
      type: 'market.quality',
      environment_id: 'env-1',
      stream_id: 's',
      stream_sequence: 2,
      event_id: 'q-1',
      event_ts_ms: 1_200,
      published_ts_ms: 1_200,
      payload: { quality_status: 'STALE', reason: 'market data is stale' },
      instrument_id: INSTRUMENT,
    })
    render(<MarketPage />)
    expect(screen.getByRole('alert')).toHaveTextContent(/模拟撮合已暂停/)
  })

  test('offline connection shows the reconnect notice', () => {
    useConnectionStore.getState().update({ status: 'closed' })
    render(<MarketPage />)
    expect(screen.getByRole('status')).toHaveTextContent(/连接断开/)
  })
})
