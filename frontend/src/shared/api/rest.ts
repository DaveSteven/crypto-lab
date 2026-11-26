import type {
  Account,
  AssetBalance,
  CandleHistoryResponse,
  Environment,
  ExecutionRecord,
  PaperOrder,
  Position,
  Snapshot,
  TopicFilter,
} from './schemas'
import {
  ApiErrorEnvelope,
  Account as AccountSchema,
  AssetBalance as AssetBalanceSchema,
  CandleHistoryResponse as CandleHistorySchema,
  Environment as EnvironmentSchema,
  ExecutionRecord as ExecutionRecordSchema,
  PaperOrder as PaperOrderSchema,
  Position as PositionSchema,
  Snapshot as SnapshotSchema,
} from './schemas'

/** Error parsed from the docs/09 §6 error envelope. */
export class ApiError extends Error {
  readonly code: string
  readonly details: Record<string, unknown>
  readonly requestId: string
  readonly status: number

  constructor(status: number, code: string, message: string, requestId: string, details: Record<string, unknown>) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.requestId = requestId
    this.details = details
  }
}

export interface RestClientOptions {
  baseUrl?: string
  fetch?: typeof fetch
  idempotencyKeyGenerator?: () => string
}

export type OrderCreateRequest = {
  account_id: string
  instrument_id: string
  side: 'BUY' | 'SELL'
  order_type: 'MARKET' | 'LIMIT'
  quantity: string
  limit_price?: string
  max_quote_budget?: string
  latency_preset?: 'IDEAL' | 'FAST' | 'NORMAL' | 'MEDIUM' | 'SLOW' | 'HIGH' | 'CUSTOM'
  custom_latency_ms?: number
}

type Query = Record<string, string | number | undefined>

/**
 * Thin REST client for the docs/09 contract.
 *
 * Decimal fields stay strings; every response body is validated with the
 * Zod contract schemas before being returned to callers.
 */
export class RestClient {
  private readonly baseUrl: string
  private readonly fetchImpl: typeof fetch
  private readonly newIdempotencyKey: () => string

  constructor(options: RestClientOptions = {}) {
    this.baseUrl = options.baseUrl ?? ''
    this.fetchImpl = options.fetch ?? ((input, init) => fetch(input, init))
    this.newIdempotencyKey = options.idempotencyKeyGenerator ?? (() => crypto.randomUUID())
  }

  async healthReady(): Promise<{ status: string }> {
    const body = await this.request('GET', '/health/ready', undefined, 200, undefined, false)
    return body as { status: string }
  }

  async createEnvironment(name: string): Promise<Environment> {
    const body = await this.request(
      'POST',
      '/api/v1/environments',
      { name },
      201,
      this.newIdempotencyKey(),
    )
    return EnvironmentSchema.parse(body)
  }

  async getEnvironment(environmentId: string): Promise<Environment> {
    const body = await this.request('GET', `/api/v1/environments/${environmentId}`)
    return EnvironmentSchema.parse(body)
  }

  async createAccount(
    environmentId: string,
    request: { exchange_id: string; name: string; initial_asset: string; initial_amount: string },
  ): Promise<Account & { balances?: AssetBalance[] }> {
    const body = await this.request(
      'POST',
      `/api/v1/environments/${environmentId}/accounts`,
      request,
      201,
      this.newIdempotencyKey(),
    )
    return AccountSchema.parse(body)
  }

  async listAccounts(environmentId: string, limit = 50): Promise<Account[]> {
    const body = await this.request('GET', `/api/v1/environments/${environmentId}/accounts?limit=${limit}`)
    return parseArray(AccountSchema, body)
  }

  async balances(environmentId: string, accountId: string): Promise<AssetBalance[]> {
    const body = await this.request(
      'GET',
      `/api/v1/environments/${environmentId}/accounts/${accountId}/balances`,
    )
    return parseArray(AssetBalanceSchema, body)
  }

  async positions(environmentId: string, accountId: string): Promise<Position[]> {
    const body = await this.request(
      'GET',
      `/api/v1/environments/${environmentId}/accounts/${accountId}/positions`,
    )
    return parseArray(PositionSchema, body)
  }

  async createOrder(environmentId: string, request: OrderCreateRequest): Promise<PaperOrder> {
    const body = await this.request(
      'POST',
      `/api/v1/environments/${environmentId}/orders`,
      request,
      201,
      this.newIdempotencyKey(),
    )
    return PaperOrderSchema.parse(body)
  }

  async listOrders(
    environmentId: string,
    filters: { limit?: number; account_id?: string; status?: string } = {},
  ): Promise<PaperOrder[]> {
    const body = await this.request(
      'GET',
      `/api/v1/environments/${environmentId}/orders${queryString(filters)}`,
    )
    return parseArray(PaperOrderSchema, body)
  }

  async getOrder(environmentId: string, orderId: string): Promise<PaperOrder> {
    const body = await this.request('GET', `/api/v1/environments/${environmentId}/orders/${orderId}`)
    return PaperOrderSchema.parse(body)
  }

  async cancelOrder(environmentId: string, orderId: string): Promise<PaperOrder> {
    const body = await this.request(
      'POST',
      `/api/v1/environments/${environmentId}/orders/${orderId}/cancel`,
      {},
      200,
      this.newIdempotencyKey(),
    )
    return PaperOrderSchema.parse(body)
  }

  async listExecutions(
    environmentId: string,
    filters: { limit?: number; account_id?: string; order_id?: string } = {},
  ): Promise<ExecutionRecord[]> {
    const body = await this.request(
      'GET',
      `/api/v1/environments/${environmentId}/executions${queryString(filters)}`,
    )
    return parseArray(ExecutionRecordSchema, body)
  }

  async getExecution(environmentId: string, executionId: string): Promise<ExecutionRecord> {
    const body = await this.request(
      'GET',
      `/api/v1/environments/${environmentId}/executions/${executionId}`,
    )
    return ExecutionRecordSchema.parse(body)
  }

  /** Consistency snapshot for the docs/10 §8.1 resync flow. */
  async snapshot(environmentId: string, accountId: string): Promise<Snapshot> {
    const body = await this.request(
      'GET',
      `/api/v1/environments/${environmentId}/snapshot?account_id=${encodeURIComponent(accountId)}`,
    )
    return SnapshotSchema.parse(body)
  }

  async candleHistory(
    instrumentId: string,
    interval: string,
    params: { limit?: number; before?: number; after?: number } = {},
  ): Promise<CandleHistoryResponse> {
    const body = await this.request(
      'GET',
      `/api/v1/market/candles${queryString({ instrument_id: instrumentId, interval, ...params })}`,
    )
    return CandleHistorySchema.parse(body)
  }

  private async request(
    method: string,
    path: string,
    body?: unknown,
    expectedStatus = 200,
    idempotencyKey?: string,
    parseErrors = true,
  ): Promise<unknown> {
    const headers: Record<string, string> = { 'X-Request-ID': crypto.randomUUID() }
    if (idempotencyKey !== undefined) headers['Idempotency-Key'] = idempotencyKey
    if (body !== undefined) headers['Content-Type'] = 'application/json'
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    const text = await response.text()
    const parsed: unknown = text ? JSON.parse(text) : undefined
    if (response.status !== expectedStatus) {
      if (parseErrors) {
        const envelope = ApiErrorEnvelope.safeParse(parsed)
        if (envelope.success) {
          const error = envelope.data.error
          throw new ApiError(
            response.status,
            error.code,
            error.message,
            error.request_id,
            error.details,
          )
        }
      }
      throw new ApiError(response.status, 'UNKNOWN_ERROR', `unexpected status ${response.status}`, '', {})
    }
    return parsed
  }
}

function parseArray<T>(schema: { parse: (value: unknown) => T }, body: unknown): T[] {
  const items = (body as { items?: unknown }).items
  if (!Array.isArray(items)) throw new Error('expected an items array in list response')
  return items.map((item) => schema.parse(item))
}

function queryString(params: Query): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

export type { TopicFilter }
