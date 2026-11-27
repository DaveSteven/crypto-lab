import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, test } from 'vitest'
import { useSessionStore } from '@/app/sessionStore'
import { JournalDetailPage } from './JournalDetailPage'
import { JournalListPage } from './JournalListPage'

const server = setupServer()
beforeAll(() => server.listen())
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

const journal = {
  journal_id: 'journal-1',
  environment_id: 'env-1',
  account_id: 'account-1',
  instrument_id: 'okx:SPOT:BTC/USDT',
  title: 'Support bounce plan',
  status: 'DRAFT',
  version: 1,
  current_plan_revision_id: null,
  timeframe: '1h',
  market_trend: 'UPTREND',
  trade_reason: '观察支撑区域反应',
  entry_conditions: null,
  execution_notes: null,
  review_summary: null,
  archive_reason: null,
  created_ts_ms: 1_000,
  updated_ts_ms: 2_000,
  ready_ts_ms: null,
  activated_ts_ms: null,
  closed_ts_ms: null,
  reviewed_ts_ms: null,
  cancelled_ts_ms: null,
}

function renderRoutes(entry = '/journal') {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/journal" element={<JournalListPage />} />
          <Route path="/journal/:journalId" element={<JournalDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useSessionStore.setState({ session: { environmentId: 'env-1', accountId: 'account-1' } })
  server.use(
    http.get('*/api/v1/environments/env-1/accounts/account-1/journals', () =>
      HttpResponse.json({ items: [journal] }),
    ),
    http.get('*/api/v1/environments/env-1/accounts/account-1/journals/journal-1', () =>
      HttpResponse.json({ ...journal, plan_revisions: [] }),
    ),
  )
})

describe('Journal list and detail', () => {
  test('lists real Journal fields and opens the scoped detail page', async () => {
    const user = userEvent.setup()
    renderRoutes()
    const table = await screen.findByRole('table')
    const row = within(table).getByText('Support bounce plan').closest('tr')!
    expect(row).toHaveTextContent('草稿')
    expect(row).toHaveTextContent('BTC/USDT')
    expect(row).toHaveTextContent('1h')
    await user.click(within(row).getByRole('button', { name: 'Support bounce plan' }))
    expect(await screen.findByRole('heading', { name: 'Support bounce plan' })).toBeVisible()
    expect(screen.getByText('观察支撑区域反应')).toBeVisible()
    expect(screen.getByText(/Trade Plan Editor 将在 Task 1.14.4/)).toBeVisible()
    expect(screen.getByText(/不会推测或伪造成交结果/)).toBeVisible()
  })

  test('creates a Draft once and navigates without exposing planner inputs', async () => {
    const user = userEvent.setup()
    let posts = 0
    server.use(
      http.post('*/api/v1/environments/env-1/accounts/account-1/journals', async ({ request }) => {
        posts += 1
        const body = (await request.json()) as Record<string, unknown>
        expect(body).toEqual({
          title: 'Breakout observation',
          instrument_id: 'okx:SPOT:BTC/USDT',
          timeframe: '1h',
        })
        return HttpResponse.json({ ...journal, title: body.title }, { status: 201 })
      }),
    )
    renderRoutes()
    await user.click(screen.getByRole('button', { name: '新建交易日志' }))
    await user.type(screen.getByLabelText('日志标题'), 'Breakout observation')
    await user.click(screen.getByRole('button', { name: '保存 Draft' }))
    await waitFor(() => expect(posts).toBe(1))
    expect(await screen.findByRole('heading', { name: 'Support bounce plan' })).toBeVisible()
    expect(screen.queryByLabelText('计划入场价格')).toBeNull()
  })

  test('shows an honest empty state rather than invented metrics', async () => {
    server.use(
      http.get('*/api/v1/environments/env-1/accounts/account-1/journals', () =>
        HttpResponse.json({ items: [] }),
      ),
    )
    renderRoutes()
    expect(await screen.findByText(/暂无符合条件的交易日志/)).toBeVisible()
    expect(screen.queryByText(/累计收益/)).toBeNull()
  })
})
