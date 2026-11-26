import { RestClient } from '@/shared/api/rest'
import { TradingStateSync } from '@/shared/api/sync'
import { WSClient } from '@/shared/api/ws'
import type { TopicFilter } from '@/shared/api/schemas'
import { useConnectionStore } from '@/app/connectionStore'
import { useMarketStore } from '@/features/market/marketStore'
import { useTradingStore } from '@/features/trading/tradingStore'

const RESIDENT_INTERVAL = '1m'

export interface GatewayDeps {
  createRest?: () => RestClient
  createClient?: (url: string) => WSClient
  createSync?: (
    client: WSClient,
    rest: RestClient,
    environmentId: string,
    accountId: string,
  ) => TradingStateSync
}

/**
 * One realtime gateway per browser tab: a single WS connection bound to the
 * active environment, feeding the connection/trading stores. Never created
 * per page or per component (docs/10: one connection belongs to one
 * environment; the browser is a consumer only).
 */
export class RealtimeGateway {
  private client: WSClient | null = null
  private sync: TradingStateSync | null = null
  private connectedFor: string | null = null
  private readonly deps: GatewayDeps
  private dynamicCandle: { instrumentId: string; interval: string } | null = null
  private pendingCandle: { instrumentId: string; interval: string } | null = null

  constructor(deps: GatewayDeps = {}) {
    this.deps = deps
  }

  get activeKey(): string | null {
    return this.connectedFor
  }

  start(environmentId: string, accountId: string, instruments: string[] = []): void {
    const key = `${environmentId}:${accountId}`
    if (this.connectedFor === key && this.client !== null) return
    this.stop()

    useConnectionStore.getState().update({
      status: 'connecting',
      streamId: null,
      lastEventTsMs: null,
      resyncReason: null,
    })

    const rest = this.deps.createRest?.() ?? new RestClient()
    const trading = useTradingStore.getState()
    trading.reset()

    const client =
      this.deps.createClient?.(websocketUrl(environmentId)) ??
      new WSClient({ url: websocketUrl(environmentId) })

    client.onStatus((status) => useConnectionStore.getState().update({ status }))
    client.onMessage((message) => {
      if (message.type === 'error') {
        if (message.code === 'SUBSCRIPTION_LIMIT') {
          useMarketStore.getState().setCandleSubscriptionError(message.message ?? message.code)
        }
        return
      }
      if (!('event_ts_ms' in message)) return
      useConnectionStore.getState().update({ lastEventTsMs: message.event_ts_ms })
      if (
        message.type === 'market.ticker' ||
        message.type === 'market.trade' ||
        message.type === 'market.order_book' ||
        message.type === 'market.candle' ||
        message.type === 'market.quality'
      ) {
        useMarketStore.getState().applyMarketEvent(message)
      }
    })
    client.onResync((reason) => useConnectionStore.getState().update({ resyncReason: reason }))

    // Trading topics scope to the account; market topics to the instruments
    // shown by the app (docs/10 §4.1).
    const topics: TopicFilter[] = [
      { name: 'orders', account_id: accountId },
      { name: 'balances', account_id: accountId },
      { name: 'executions', account_id: accountId },
      { name: 'positions', account_id: accountId },
    ]
    for (const instrumentId of instruments) {
      topics.push(
        { name: 'market.ticker', instrument_id: instrumentId },
        { name: 'market.trade', instrument_id: instrumentId },
        { name: 'market.order_book', instrument_id: instrumentId },
        // Resident 1m channel; other intervals are subscribed on demand (ADR 0008).
        { name: 'market.candle', instrument_id: instrumentId, interval: RESIDENT_INTERVAL },
        { name: 'market.quality', instrument_id: instrumentId },
      )
    }
    client.setTopics(topics)

    this.sync = new TradingStateSync(client, rest, environmentId, accountId, {
      applySnapshot: (snapshot) => useTradingStore.getState().applySnapshot(snapshot),
      applyEvent: (event) => useTradingStore.getState().applyEvent(event),
    })
    this.client = client
    this.connectedFor = key

    // After every (re)subscription, restore consistency from REST first.
    client.onStatus((status) => {
      if (status === 'subscribed') void this.sync?.resync()
    })

    client.connect()
    if (this.pendingCandle !== null) {
      const pending = this.pendingCandle
      this.pendingCandle = null
      this.setCandleInterval(pending.instrumentId, pending.interval)
    }
  }

  /**
   * Make `interval` the live candle channel for the instrument. The previous
   * dynamic interval is released (the server keeps it 30s before dropping the
   * upstream channel). The resident 1m channel is never unsubscribed.
   */
  setCandleInterval(instrumentId: string, interval: string): void {
    useMarketStore.getState().setCandleSubscriptionError(null)
    const client = this.client
    if (client === null) {
      this.pendingCandle = { instrumentId, interval }
      return
    }
    const previous = this.dynamicCandle
    if (previous !== null && (previous.instrumentId !== instrumentId || previous.interval !== interval)) {
      client.unsubscribe([
        { name: 'market.candle', instrument_id: previous.instrumentId, interval: previous.interval },
      ])
      this.dynamicCandle = null
    }
    if (interval === RESIDENT_INTERVAL) return
    client.addTopics([{ name: 'market.candle', instrument_id: instrumentId, interval }])
    this.dynamicCandle = { instrumentId, interval }
  }

  stop(): void {
    this.dynamicCandle = null
    this.client?.stop()
    this.client = null
    this.sync = null
    this.connectedFor = null
  }

  /** Manual resync entry (e.g. a refresh button next to the order list). */
  resyncNow(): Promise<void> {
    if (this.sync === null) return Promise.resolve()
    return this.sync.resync()
  }
}

export function websocketUrl(environmentId: string): string {
  const protocol = typeof location !== 'undefined' && location.protocol === 'https:' ? 'wss' : 'ws'
  const host = typeof location !== 'undefined' ? location.host : '127.0.0.1:5173'
  return `${protocol}://${host}/api/v1/ws/environments/${environmentId}`
}

export const gateway = new RealtimeGateway()
