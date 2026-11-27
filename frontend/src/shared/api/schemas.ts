import { z } from 'zod'

/**
 * Contract schemas derived from docs/09 (REST) and docs/10 (WebSocket).
 *
 * All monetary fields arrive as decimal strings per the REST contract;
 * they must never be parsed into floats. Types are inferred with z.infer
 * so no second hand-written interface can drift from these schemas.
 */

export const DecimalString = z.string()

export const OrderSide = z.enum(['BUY', 'SELL'])
export const OrderType = z.enum(['MARKET', 'LIMIT'])
export const OrderStatus = z.enum([
  'PENDING_EXECUTION',
  'OPEN',
  'PARTIALLY_FILLED',
  'FILLED',
  'CANCELED',
  'REJECTED',
])
export const LatencyPreset = z.enum([
  'IDEAL',
  'FAST',
  'NORMAL',
  'MEDIUM',
  'SLOW',
  'HIGH',
  'CUSTOM',
])

export const ApiErrorEnvelope = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    details: z.record(z.string(), z.unknown()).default({}),
    request_id: z.string(),
  }),
})

export const Environment = z.object({
  environment_id: z.string(),
  name: z.string(),
  status: z.string(),
  created_ts_ms: z.number(),
  updated_ts_ms: z.number(),
  state_version: z.number().optional(),
})

export const Account = z.object({
  account_id: z.string(),
  exchange_id: z.string(),
  name: z.string(),
  created_ts_ms: z.number(),
})

export const AssetBalance = z.object({
  asset: z.string(),
  available: DecimalString,
  locked: DecimalString,
})

export const PaperOrder = z.object({
  order_id: z.string(),
  account_id: z.string(),
  instrument_id: z.string(),
  side: OrderSide,
  order_type: OrderType,
  quantity: DecimalString,
  limit_price: DecimalString.nullable().optional(),
  reference_price: DecimalString,
  max_quote_budget: DecimalString.nullable().optional(),
  reserved_asset: z.string(),
  reserved_amount: DecimalString,
  filled_quantity: DecimalString,
  cumulative_quote_amount: DecimalString,
  cumulative_fee: DecimalString,
  average_fill_price: DecimalString.nullable().optional(),
  time_in_force: z.string().default('GTC'),
  fee_schedule_id: z.string().nullable().optional(),
  reserved_fee_rate: DecimalString,
  status: OrderStatus,
  submitted_ts_ms: z.number(),
  scheduled_execution_ts_ms: z.number().nullable().optional(),
  market_entry_ts_ms: z.number().nullable().optional(),
  executed_ts_ms: z.number().nullable().optional(),
  configured_latency_ms: z.number().nullable().optional(),
  actual_simulated_delay_ms: z.number().nullable().optional(),
  scheduler_lag_ms: z.number().nullable().optional(),
  submission_quote_event_id: z.string().nullable().optional(),
  execution_quote_event_id: z.string().nullable().optional(),
  termination_reason: z.string().nullable().optional(),
  order_sequence: z.number(),
  created_ts_ms: z.number(),
  updated_ts_ms: z.number(),
})

export const ExecutionRecord = z.object({
  execution_id: z.string(),
  order_id: z.string(),
  account_id: z.string(),
  instrument_id: z.string(),
  side: OrderSide,
  price: DecimalString,
  quantity: DecimalString,
  quote_amount: DecimalString,
  fee_asset: z.string(),
  fee_amount: DecimalString,
  executed_ts_ms: z.number(),
})

export const Position = z.object({
  account_id: z.string(),
  instrument_id: z.string(),
  base_asset: z.string(),
  quote_asset: z.string().optional(),
  quantity: DecimalString,
  average_cost: DecimalString.nullable().optional(),
  cost_basis: DecimalString,
  realized_pnl: DecimalString,
  cumulative_fees: DecimalString,
})

export const PnlInstrument = z.object({
  instrument_id: z.string(),
  base_asset: z.string().optional(),
  quote_asset: z.string(),
  quantity: DecimalString.optional(),
  realized_pnl: DecimalString,
  cumulative_fees: DecimalString,
})

/** Account lifetime realized PnL derived from the full Fill History (docs/09 §4.3.1). */
export const AccountPnl = z.object({
  status: z.enum(['AVAILABLE', 'UNAVAILABLE']),
  reason: z.string().optional(),
  state_version: z.number().optional(),
  as_of_ts_ms: z.number().optional(),
  scope: z.string().optional(),
  cost_method: z.string().optional(),
  cumulative_realized_pnl_by_currency: z.record(z.string(), DecimalString).optional(),
  cumulative_fees_by_currency: z.record(z.string(), DecimalString).optional(),
  instruments: z.array(PnlInstrument).optional(),
})

export const Snapshot = z.object({
  environment_id: z.string(),
  account_id: z.string(),
  state_version: z.number(),
  account: z.unknown(),
  balances: z.array(AssetBalance),
  orders: z.array(PaperOrder),
  executions: z.array(ExecutionRecord),
  positions: z.array(Position),
  pnl: AccountPnl.optional(),
})

export const Candle = z.object({
  interval: z.string(),
  open_ts_ms: z.number(),
  close_ts_ms: z.number(),
  open: DecimalString,
  high: DecimalString,
  low: DecimalString,
  close: DecimalString,
  base_volume: DecimalString.nullable().optional(),
  quote_volume: DecimalString.nullable().optional(),
  trade_count: z.number().nullable().optional(),
  is_closed: z.boolean(),
})

export const CandleEnvelope = z.object({
  event_id: z.string(),
  event_type: z.string(),
  instrument_id: z.string(),
  exchange_ts_ms: z.number().nullable().optional(),
  received_ts_ms: z.number(),
  quality_status: z.string(),
  payload: Candle,
})

export const CandleHistoryResponse = z.object({
  items: z.array(CandleEnvelope),
  source: z.string(),
})

export const Ticker = z.object({
  bid: DecimalString.nullable().optional(),
  bid_size: DecimalString.nullable().optional(),
  ask: DecimalString.nullable().optional(),
  ask_size: DecimalString.nullable().optional(),
  last: DecimalString.nullable().optional(),
  open_24h: DecimalString.nullable().optional(),
  high_24h: DecimalString.nullable().optional(),
  low_24h: DecimalString.nullable().optional(),
  base_volume_24h: DecimalString.nullable().optional(),
  quote_volume_24h: DecimalString.nullable().optional(),
})

export const Trade = z.object({
  trade_id: z.string(),
  price: DecimalString,
  quantity: DecimalString,
  side: z.enum(['BUY', 'SELL']),
})

export const PriceLevel = z.object({
  price: DecimalString,
  quantity: DecimalString,
})

export const OrderBookPayload = z.object({
  bids: z.array(PriceLevel),
  asks: z.array(PriceLevel),
  depth: z.number(),
  sequence_id: z.string().nullable(),
  quality_status: z.string(),
  received_ts_ms: z.number(),
})

export const QualityPayload = z.object({
  quality_status: z.enum(['VALID', 'INVALID', 'STALE', 'INCOMPLETE', 'UNSYNCED']),
  reason: z.string(),
})

export type Environment = z.infer<typeof Environment>
export type Account = z.infer<typeof Account>
export type AssetBalance = z.infer<typeof AssetBalance>
export type PaperOrder = z.infer<typeof PaperOrder>
export type ExecutionRecord = z.infer<typeof ExecutionRecord>
export type Position = z.infer<typeof Position>
export type Snapshot = z.infer<typeof Snapshot>
export type AccountPnl = z.infer<typeof AccountPnl>
export type PnlInstrument = z.infer<typeof PnlInstrument>

export const FeedInstrument = z.object({
  instrument_id: z.string(),
  exchange_id: z.string(),
  market_type: z.string(),
  base_asset: z.string(),
  quote_asset: z.string(),
})
export const MarketInstruments = z.object({
  feed_enabled: z.boolean(),
  items: z.array(FeedInstrument),
})
export type FeedInstrument = z.infer<typeof FeedInstrument>
export type MarketInstruments = z.infer<typeof MarketInstruments>
export type Candle = z.infer<typeof Candle>
export type CandleEnvelope = z.infer<typeof CandleEnvelope>
export type CandleHistoryResponse = z.infer<typeof CandleHistoryResponse>
export type Ticker = z.infer<typeof Ticker>
export type OrderTopicPayload = z.infer<typeof PaperOrder>
export type BalancesTopicPayload = { asset: string; available: string; locked: string }
export type ExecutionsTopicPayload = z.infer<typeof ExecutionRecord>
export type PositionsTopicPayload = z.infer<typeof Position>

export const JournalStatus = z.enum([
  'DRAFT',
  'READY',
  'ACTIVE',
  'CLOSED',
  'REVIEWED',
  'CANCELLED',
])

export const PlanRevision = z.object({
  plan_revision_id: z.string(),
  journal_id: z.string(),
  revision_number: z.number(),
  entry_price: DecimalString,
  planned_position_notional: DecimalString,
  stop_loss_price: DecimalString,
  take_profit_price: DecimalString,
  max_position_notional: DecimalString,
  max_account_risk_rate: DecimalString,
  min_reward_risk_ratio: DecimalString,
  validation_status: z.enum(['PASS', 'FAIL', 'UNAVAILABLE']),
  calculator_version: z.string(),
  revision_reason: z.string(),
  is_initial_confirmed: z.boolean(),
  created_ts_ms: z.number(),
  confirmed_ts_ms: z.number().nullable().optional(),
  context_json: z.record(z.string(), z.unknown()),
  calculation_json: z.record(z.string(), z.unknown()),
  validation_results_json: z.record(z.string(), z.unknown()),
})

export const TradingJournal = z.object({
  journal_id: z.string(),
  environment_id: z.string(),
  account_id: z.string(),
  instrument_id: z.string(),
  title: z.string(),
  status: JournalStatus,
  version: z.number(),
  current_plan_revision_id: z.string().nullable().optional(),
  timeframe: z.string().nullable().optional(),
  market_trend: z.string().nullable().optional(),
  trade_reason: z.string().nullable().optional(),
  entry_conditions: z.string().nullable().optional(),
  execution_notes: z.string().nullable().optional(),
  review_summary: z.string().nullable().optional(),
  archive_reason: z.string().nullable().optional(),
  created_ts_ms: z.number(),
  updated_ts_ms: z.number(),
  ready_ts_ms: z.number().nullable().optional(),
  activated_ts_ms: z.number().nullable().optional(),
  closed_ts_ms: z.number().nullable().optional(),
  reviewed_ts_ms: z.number().nullable().optional(),
  cancelled_ts_ms: z.number().nullable().optional(),
  plan_revisions: z.array(PlanRevision).optional(),
})

export type JournalStatus = z.infer<typeof JournalStatus>
export type PlanRevision = z.infer<typeof PlanRevision>
export type TradingJournal = z.infer<typeof TradingJournal>

const PlannerValidation = z.object({
  status: z.enum(['PASS', 'FAIL', 'UNAVAILABLE']),
  reason: z.string(),
})

export const PlannerContext = z.object({
  environment_id: z.string(),
  account_id: z.string(),
  instrument_id: z.string(),
  as_of_ts_ms: z.number(),
  quote_asset: z.string(),
  available_quote_balance: DecimalString,
  effective_account_equity: DecimalString.nullable(),
  valuation_status: z.enum(['COMPLETE', 'INCOMPLETE']),
  unavailable_assets: z.array(z.string()),
  fee_schedule: z.object({
    schedule_id: z.string(),
    maker_fee_rate: DecimalString,
    taker_fee_rate: DecimalString,
    conservative_fee_rate: DecimalString,
    fee_asset_mode: z.string(),
  }),
  market_rules: z.object({
    instrument_id: z.string(),
    rules_id: z.string(),
    price_increment: DecimalString,
    quantity_increment: DecimalString,
    min_quantity: DecimalString,
    min_notional: DecimalString.nullable(),
  }),
  market_status: z.enum(['VALID', 'UNAVAILABLE']),
  market_event_id: z.string().nullable(),
  market_updated_ts_ms: z.number().nullable(),
})

export const PlannerPreview = z.object({
  calculator_version: z.string(),
  validation_status: z.enum(['PASS', 'FAIL', 'UNAVAILABLE']),
  validations: z.record(z.string(), PlannerValidation),
  calculation: z.object({
    quantity: DecimalString.nullable(),
    entry_notional: DecimalString.nullable(),
    entry_fee: DecimalString.nullable(),
    exit_fee_at_take_profit: DecimalString.nullable(),
    exit_fee_at_stop_loss: DecimalString.nullable(),
    estimated_net_profit: DecimalString.nullable(),
    estimated_net_loss: DecimalString.nullable(),
    net_reward_risk_ratio: DecimalString.nullable(),
    account_risk_ratio: DecimalString.nullable(),
    position_ratio: DecimalString.nullable(),
    maximum_allowed_position_notional: DecimalString.nullable(),
  }),
  context: PlannerContext,
})

export type PlannerContext = z.infer<typeof PlannerContext>
export type PlannerPreview = z.infer<typeof PlannerPreview>

// ---------------------------------------------------------------------------
// WebSocket envelope (docs/10 §3)
// ---------------------------------------------------------------------------

const EnvelopeBase = z.object({
  protocol_version: z.string(),
  environment_id: z.string(),
  stream_id: z.string(),
  stream_sequence: z.number().int().positive(),
  event_id: z.string(),
  event_ts_ms: z.number(),
  published_ts_ms: z.number(),
  payload: z.record(z.string(), z.unknown()),
  instrument_id: z.string().nullable().optional(),
  account_id: z.string().nullable().optional(),
  order_id: z.string().nullable().optional(),
  interval: z.string().nullable().optional(),
  /** Present on business messages actually delivered to this connection. */
  delivery_sequence: z.number().int().positive().optional(),
  state_version: z.number().nullable().optional(),
  transaction_id: z.string().nullable().optional(),
  event_index: z.number().nullable().optional(),
})

export const MarketEventMessage = EnvelopeBase.extend({
  type: z.enum([
    'market.ticker',
    'market.trade',
    'market.order_book',
    'market.candle',
    'market.quality',
  ]),
})

export const TradingEventMessage = EnvelopeBase.extend({
  type: z.enum(['orders', 'balances', 'executions', 'positions']),
})

export const SessionReadyMessage = z.object({
  protocol_version: z.string(),
  type: z.literal('session.ready'),
  environment_id: z.string(),
  stream_id: z.string(),
  stream_sequence: z.number(),
})

export const SubscriptionAckMessage = z.object({
  type: z.literal('subscription.ack'),
  request_id: z.string(),
  replayed: z.number().optional(),
})

export const PongMessage = z.object({
  type: z.literal('pong'),
  request_id: z.string(),
})

export const HeartbeatMessage = z.object({
  type: z.literal('heartbeat'),
  heartbeat_id: z.string(),
})

export const ErrorMessage = z.object({
  type: z.literal('error'),
  code: z.string(),
  message: z.string(),
  request_id: z.string().optional(),
})

export const ResyncRequiredMessage = z.object({
  type: z.literal('resync.required'),
  reason: z.string(),
})

export const ServerMessage = z.discriminatedUnion('type', [
  MarketEventMessage,
  TradingEventMessage,
  SessionReadyMessage,
  SubscriptionAckMessage,
  PongMessage,
  HeartbeatMessage,
  ErrorMessage,
  ResyncRequiredMessage,
])

export type MarketEvent = z.infer<typeof MarketEventMessage>
export type TradingEvent = z.infer<typeof TradingEventMessage>
export type ServerMessage = z.infer<typeof ServerMessage>

export type TopicFilter = {
  name: string
  instrument_id?: string
  account_id?: string
  interval?: string
}

export type ResumeFrom = { stream_id: string; stream_sequence: number }
