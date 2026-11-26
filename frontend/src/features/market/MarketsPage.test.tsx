import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, test } from 'vitest'
import { MarketsPage } from './MarketsPage'
import { useInstrumentStore } from './instrumentStore'
import { useMarketStore } from './marketStore'

const server = setupServer()
beforeAll(() => server.listen())
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

const item = (base: string) => ({
  instrument_id: `okx:SPOT:${base}/USDT`,
  exchange_id: 'okx',
  market_type: 'SPOT',
  base_asset: base,
  quote_asset: 'USDT',
})

function ticker(base: string, last: string, open: string, volume: string) {
  useMarketStore.getState().applyMarketEvent({
    protocol_version: '1.0.0',
    type: 'market.ticker',
    environment_id: 'e',
    stream_id: 's',
    stream_sequence: 1,
    event_id: `t-${base}`,
    event_ts_ms: 1,
    published_ts_ms: 1,
    payload: { last, open_24h: open, base_volume_24h: volume },
    instrument_id: `okx:SPOT:${base}/USDT`,
  } as never)
}

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/markets']}>
        <Routes>
          <Route path="/markets" element={<MarketsPage />} />
          <Route path="/trading" element={<div>交易页</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useMarketStore.getState().reset()
  useInstrumentStore.setState({ instrumentId: 'okx:SPOT:BTC/USDT' })
  server.use(
    http.get('*/api/v1/market/instruments', () =>
      HttpResponse.json({ feed_enabled: true, items: [item('BTC'), item('ETH')] }),
    ),
  )
})

describe('MarketsPage', () => {
  test('lists only feed instruments with real ticker fields and -- for missing data', async () => {
    ticker('BTC', '61000', '60000', '1234.5')
    renderPage()
    const btc = (await screen.findByText('BTC/USDT')).closest('tr')!
    expect(within(btc).getByText('61000')).toBeVisible()
    expect(within(btc).getByText('+1.67%')).toBeVisible()
    expect(within(btc).getByText('有效')).toBeVisible() // live ticker, no degrade event
    const eth = screen.getByText('ETH/USDT').closest('tr')!
    expect(within(eth).getAllByText('--').length).toBeGreaterThanOrEqual(3)
    expect(within(eth).getByText('等待行情')).toBeVisible()
    expect(screen.queryByText('SOL/USDT')).toBeNull()
  })

  test('search filters and sorting keeps missing values last', async () => {
    const user = userEvent.setup()
    ticker('ETH', '1700', '1600', '50')
    renderPage()
    await screen.findByText('BTC/USDT')
    await user.type(screen.getByLabelText('搜索交易对'), 'eth')
    expect(screen.queryByText('BTC/USDT')).toBeNull()
    expect(screen.getByText('ETH/USDT')).toBeVisible()
    await user.clear(screen.getByLabelText('搜索交易对'))
    await user.click(screen.getByRole('button', { name: '最新价' }))
    await user.click(screen.getByRole('button', { name: /最新价/ })) // descending
    const rows = screen.getAllByRole('row').slice(1)
    expect(within(rows[0]).getByText('ETH/USDT')).toBeVisible() // has a price
    expect(within(rows[1]).getByText('BTC/USDT')).toBeVisible() // missing price sorts last
  })

  test('clicking a pair selects it and opens the Trading page', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(await screen.findByRole('button', { name: 'ETH/USDT' }))
    expect(useInstrumentStore.getState().instrumentId).toBe('okx:SPOT:ETH/USDT')
    await waitFor(() => expect(screen.getByText('交易页')).toBeVisible())
  })

  test('feed disabled shows an honest empty state', async () => {
    server.use(
      http.get('*/api/v1/market/instruments', () => HttpResponse.json({ feed_enabled: false, items: [] })),
    )
    renderPage()
    expect(await screen.findByText(/行情 Feed 未启用/)).toBeVisible()
  })
})
