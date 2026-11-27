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
    http.get('*/api/v1/environments/env-1/accounts/account-1/journals/trade-planner/context', () =>
      HttpResponse.json({
        environment_id: 'env-1', account_id: 'account-1', instrument_id: 'okx:SPOT:BTC/USDT',
        as_of_ts_ms: 2_000, quote_asset: 'USDT', available_quote_balance: '751',
        effective_account_equity: '751', valuation_status: 'COMPLETE', unavailable_assets: [],
        valuation_quotes: [],
        fee_schedule: { schedule_id: 'fee-v1', maker_fee_rate: '0.0008', taker_fee_rate: '0.001', conservative_fee_rate: '0.001', fee_asset_mode: 'QUOTE_ASSET' },
        market_rules: { instrument_id: 'okx:SPOT:BTC/USDT', rules_id: 'rules-v1', price_increment: '0.1', quantity_increment: '0.00000001', min_quantity: '0.00001', min_notional: null },
        market_status: 'VALID', market_event_id: 'book-1', market_updated_ts_ms: 2_000,
      }),
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
    expect(screen.getByText('Trade Planner')).toBeVisible()
    expect(screen.getByLabelText('计划入场价格')).toBeVisible()
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
    expect(screen.getByLabelText('计划入场价格')).toHaveValue('')
    expect(screen.getByRole('button', { name: '保存 Plan Revision' })).toBeDisabled()
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

  test('calculates locally, requires authoritative validation, then saves an immutable revision', async () => {
    const user = userEvent.setup()
    let previewPosts = 0
    let revisionPosts = 0
    const calculation = {
      quantity: '0.1', entry_notional: '100', entry_fee: '0.1',
      exit_fee_at_take_profit: '0.112', exit_fee_at_stop_loss: '0.095',
      estimated_net_profit: '11.788', estimated_net_loss: '5.195',
      net_reward_risk_ratio: '2.2691', account_risk_ratio: '0.006917',
      position_ratio: '0.13315', maximum_allowed_position_notional: '72.1',
    }
    const context = {
      environment_id: 'env-1', account_id: 'account-1', instrument_id: 'okx:SPOT:BTC/USDT',
      as_of_ts_ms: 2_000, quote_asset: 'USDT', available_quote_balance: '751',
      effective_account_equity: '751', valuation_status: 'COMPLETE', unavailable_assets: [], valuation_quotes: [],
      fee_schedule: { schedule_id: 'fee-v1', maker_fee_rate: '0.0008', taker_fee_rate: '0.001', conservative_fee_rate: '0.001', fee_asset_mode: 'QUOTE_ASSET' },
      market_rules: { instrument_id: 'okx:SPOT:BTC/USDT', rules_id: 'rules-v1', price_increment: '0.1', quantity_increment: '0.00000001', min_quantity: '0.00001', min_notional: null },
      market_status: 'VALID', market_event_id: 'book-1', market_updated_ts_ms: 2_000,
    }
    const validations = Object.fromEntries(['price_relationship', 'price_precision', 'minimum_quantity', 'minimum_notional', 'position_limit', 'fee_schedule', 'available_balance', 'account_risk', 'reward_risk', 'market_data'].map((key) => [key, { status: 'PASS', reason: 'ok' }]))
    server.use(
      http.post('*/journals/trade-planner/preview', async ({ request }) => {
        previewPosts += 1
        const body = (await request.json()) as Record<string, unknown>
        expect(body.max_account_risk_rate).toBe('0.005')
        return HttpResponse.json({ calculator_version: 'spot-long-v1', validation_status: 'PASS', validations, calculation, context })
      }),
      http.post('*/journals/journal-1/plan/revisions', async ({ request }) => {
        revisionPosts += 1
        const body = (await request.json()) as Record<string, unknown>
        expect(body.journal_version).toBe(1)
        return HttpResponse.json({
          plan_revision_id: 'revision-1', journal_id: 'journal-1', revision_number: 1,
          entry_price: '1000', planned_position_notional: '100', stop_loss_price: '950',
          take_profit_price: '1120', max_position_notional: '100', max_account_risk_rate: '0.005',
          min_reward_risk_ratio: '2', context_json: context, calculation_json: calculation,
          validation_results_json: validations, validation_status: 'PASS', calculator_version: 'spot-long-v1',
          revision_reason: '保存交易前风险计划', is_initial_confirmed: false,
          created_ts_ms: 2_000, confirmed_ts_ms: null, journal_version: 2,
        }, { status: 201 })
      }),
    )
    renderRoutes('/journal/journal-1')
    await screen.findByText('Trade Planner')
    await user.type(screen.getByLabelText('计划入场价格'), '1000')
    await user.type(screen.getByLabelText('计划仓位金额'), '100')
    await user.type(screen.getByLabelText('止损价格 SL'), '950')
    await user.type(screen.getByLabelText('止盈价格 TP'), '1120')
    await user.type(screen.getByLabelText('单笔仓位上限'), '100')
    await user.type(screen.getByLabelText('账户风险上限'), '0.5')
    await user.type(screen.getByLabelText('最低净收益风险比'), '2')
    expect(screen.getByText('11.79')).toBeVisible()
    expect(screen.getByRole('button', { name: '保存 Plan Revision' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: '执行权威校验' }))
    await waitFor(() => expect(previewPosts).toBe(1))
    expect(await screen.findByText('后端权威校验')).toBeVisible()
    expect(screen.getByText('数值规则通过不代表市场入场信号成立。')).toBeVisible()
    await user.click(screen.getByRole('button', { name: '保存 Plan Revision' }))
    await waitFor(() => expect(revisionPosts).toBe(1))
  })
})
