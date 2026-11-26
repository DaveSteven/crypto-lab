import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test } from 'vitest'
import { ExecutionDetailDrawer } from './ExecutionDetailDrawer'
import { ExecutionsTable } from './ExecutionsTable'
import { useDetailStore } from './detailStore'
import { useTradingStore } from './tradingStore'
import type { Snapshot } from '@/shared/api/schemas'

const SNAPSHOT = {
  environment_id: 'env-1',
  account_id: 'a-1',
  state_version: 1,
  account: {},
  balances: [],
  positions: [],
  orders: [
    {
      order_id: 'order-1',
      account_id: 'a-1',
      instrument_id: 'okx:SPOT:BTC/USDT',
      side: 'BUY',
      order_type: 'LIMIT',
      quantity: '1',
      limit_price: '100',
      reference_price: '100',
      reserved_asset: 'USDT',
      reserved_amount: '101',
      filled_quantity: '0.4',
      cumulative_quote_amount: '40',
      cumulative_fee: '0.04',
      average_fill_price: '100',
      reserved_fee_rate: '0.001',
      fee_schedule_id: 'phase1-default-v1',
      time_in_force: 'GTC',
      status: 'CANCELED',
      termination_reason: 'USER_CANCELED',
      submitted_ts_ms: 1_000,
      configured_latency_ms: 100,
      actual_simulated_delay_ms: 130,
      scheduler_lag_ms: 30,
      order_sequence: 1,
      created_ts_ms: 1_000,
      updated_ts_ms: 2_000,
    },
  ],
  executions: [
    {
      execution_id: 'fill-1',
      order_id: 'order-1',
      account_id: 'a-1',
      instrument_id: 'okx:SPOT:BTC/USDT',
      side: 'BUY',
      price: '100',
      quantity: '0.4',
      quote_amount: '40',
      fee_asset: 'USDT',
      fee_amount: '0.04',
      executed_ts_ms: 1_500,
    },
  ],
} as unknown as Snapshot

beforeEach(() => {
  useTradingStore.getState().applySnapshot(SNAPSHOT)
  useDetailStore.getState().close()
})

describe('ExecutionDetailDrawer', () => {
  test('opens from a fill, shows real fills and marks unsupported analytics', async () => {
    const user = userEvent.setup()
    render(
      <>
        <ExecutionsTable />
        <ExecutionDetailDrawer />
      </>,
    )
    expect(screen.queryByRole('dialog')).toBeNull()
    await user.click(screen.getByRole('button', { name: '详情' }))
    const drawer = screen.getByRole('dialog', { name: '订单与成交详情' })
    expect(drawer).toHaveTextContent('已取消')
    expect(drawer).toHaveTextContent('已成交 0.4，取消剩余 0.6')
    expect(drawer).toHaveTextContent('fill-1')
    expect(drawer).toHaveTextContent('后端暂未提供')
    expect(drawer).toHaveTextContent('不等于真实交易所的网络延迟')
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  test('unknown order shows a not-found hint instead of fabricating data', () => {
    useDetailStore.getState().open('missing')
    render(<ExecutionDetailDrawer />)
    expect(screen.getByText(/未找到该订单/)).toBeVisible()
  })
})
