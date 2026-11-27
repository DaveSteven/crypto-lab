import { describe, expect, test } from 'vitest'
import { formFromRevision, localPlanPreview, toPlanRequest } from './planner'

const context = {
  environment_id: 'env-1', account_id: 'account-1', instrument_id: 'okx:SPOT:BTC/USDT',
  as_of_ts_ms: 1, quote_asset: 'USDT', available_quote_balance: '751',
  effective_account_equity: '751', valuation_status: 'COMPLETE' as const, unavailable_assets: [],
  fee_schedule: { schedule_id: 'fee-v1', maker_fee_rate: '0.0008', taker_fee_rate: '0.001', conservative_fee_rate: '0.001', fee_asset_mode: 'QUOTE_ASSET' },
  market_rules: { instrument_id: 'okx:SPOT:BTC/USDT', rules_id: 'rules-v1', price_increment: '0.1', quantity_increment: '0.00000001', min_quantity: '0.00001', min_notional: null },
  market_status: 'VALID' as const, market_event_id: 'book-1', market_updated_ts_ms: 1,
}

const form = {
  entryPrice: '1000', positionNotional: '100', stopLossPrice: '950', takeProfitPrice: '1120',
  maxPositionNotional: '100', maxAccountRiskPercent: '0.5', minRewardRiskRatio: '2',
}

describe('Trade Planner local Decimal preview', () => {
  test('converts displayed risk percent to backend rate without float arithmetic', () => {
    expect(toPlanRequest(form)?.max_account_risk_rate).toBe('0.005')
  })

  test('calculates quantity, both fee scenarios and risk from Decimal strings', () => {
    const result = localPlanPreview(form, context)!
    expect(result.quantity).toBe('0.1')
    expect(result.entryFee).toBe('0.1')
    expect(result.exitFeeAtTp).toBe('0.112')
    expect(result.exitFeeAtSl).toBe('0.095')
    expect(result.netProfit).toBe('11.788')
    expect(result.netLoss).toBe('5.195')
    expect(result.maximumAllowedNotional).toBe('72.28103')
  })

  test('rejects incomplete or non-positive input and restores immutable revision values', () => {
    expect(toPlanRequest({ ...form, entryPrice: '' })).toBeNull()
    expect(toPlanRequest({ ...form, positionNotional: '0' })).toBeNull()
    expect(formFromRevision({
      entry_price: '1000', planned_position_notional: '100', stop_loss_price: '950',
      take_profit_price: '1120', max_position_notional: '100', max_account_risk_rate: '0.005',
      min_reward_risk_ratio: '2',
    }).maxAccountRiskPercent).toBe('0.5')
  })
})
