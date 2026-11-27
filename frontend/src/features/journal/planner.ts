import Decimal from 'decimal.js'
import type { PlannerContext } from '@/shared/api/schemas'
import type { TradePlanRequest } from '@/shared/api/rest'

export type PlannerForm = {
  entryPrice: string
  positionNotional: string
  stopLossPrice: string
  takeProfitPrice: string
  maxPositionNotional: string
  maxAccountRiskPercent: string
  minRewardRiskRatio: string
}

const DECIMAL = /^\d+(\.\d+)?$/

export function toPlanRequest(form: PlannerForm): TradePlanRequest | null {
  if (!Object.values(form).every((value) => DECIMAL.test(value) && new Decimal(value).gt(0))) {
    return null
  }
  return {
    entry_price: form.entryPrice,
    planned_position_notional: form.positionNotional,
    stop_loss_price: form.stopLossPrice,
    take_profit_price: form.takeProfitPrice,
    max_position_notional: form.maxPositionNotional,
    max_account_risk_rate: new Decimal(form.maxAccountRiskPercent).div(100).toString(),
    min_reward_risk_ratio: form.minRewardRiskRatio,
  }
}

export function localPlanPreview(form: PlannerForm, context: PlannerContext | undefined) {
  const request = toPlanRequest(form)
  if (request === null || context === undefined) return null
  try {
    const entry = new Decimal(request.entry_price)
    const sl = new Decimal(request.stop_loss_price)
    const tp = new Decimal(request.take_profit_price)
    const notional = new Decimal(request.planned_position_notional)
    const step = new Decimal(context.market_rules.quantity_increment)
    const fee = new Decimal(context.fee_schedule.conservative_fee_rate)
    const quantity = notional.div(entry).div(step).floor().mul(step)
    const actualNotional = entry.mul(quantity)
    const entryFee = actualNotional.mul(fee)
    const tpFee = tp.mul(quantity).mul(fee)
    const slFee = sl.mul(quantity).mul(fee)
    const netProfit = tp.minus(entry).mul(quantity).minus(entryFee).minus(tpFee)
    const netLoss = entry.minus(sl).mul(quantity).plus(entryFee).plus(slFee)
    const equity = context.effective_account_equity === null
      ? null
      : new Decimal(context.effective_account_equity)
    const balanceCap = new Decimal(context.available_quote_balance).div(new Decimal(1).plus(fee))
    const lossPerQuantity = entry.minus(sl).plus(entry.mul(fee)).plus(sl.mul(fee))
    const caps = [new Decimal(request.max_position_notional), balanceCap]
    if (equity !== null && lossPerQuantity.gt(0)) {
      caps.push(equity.mul(request.max_account_risk_rate).div(lossPerQuantity).mul(entry))
    }
    const smallestCap = Decimal.min(...caps)
    const maximumAllowedNotional = smallestCap.div(entry).div(step).floor().mul(step).mul(entry)
    return {
      quantity: quantity.toString(),
      entryFee: entryFee.toString(),
      exitFeeAtTp: tpFee.toString(),
      exitFeeAtSl: slFee.toString(),
      netProfit: netProfit.toString(),
      netLoss: netLoss.toString(),
      rewardRisk: netLoss.gt(0) ? netProfit.div(netLoss).toString() : null,
      accountRiskPercent: equity?.gt(0) ? netLoss.div(equity).mul(100).toString() : null,
      positionPercent: equity?.gt(0) ? actualNotional.div(equity).mul(100).toString() : null,
      maximumAllowedNotional: maximumAllowedNotional.toString(),
    }
  } catch {
    return null
  }
}

export function formFromRevision(revision: {
  entry_price: string
  planned_position_notional: string
  stop_loss_price: string
  take_profit_price: string
  max_position_notional: string
  max_account_risk_rate: string
  min_reward_risk_ratio: string
} | undefined): PlannerForm {
  if (revision === undefined) {
    return {
      entryPrice: '', positionNotional: '', stopLossPrice: '', takeProfitPrice: '',
      maxPositionNotional: '', maxAccountRiskPercent: '', minRewardRiskRatio: '',
    }
  }
  return {
    entryPrice: revision.entry_price,
    positionNotional: revision.planned_position_notional,
    stopLossPrice: revision.stop_loss_price,
    takeProfitPrice: revision.take_profit_price,
    maxPositionNotional: revision.max_position_notional,
    maxAccountRiskPercent: new Decimal(revision.max_account_risk_rate).mul(100).toString(),
    minRewardRiskRatio: revision.min_reward_risk_ratio,
  }
}
