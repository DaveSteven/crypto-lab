import { RestClient } from '@/api/rest'
import { TradingStateSync } from '@/api/sync'
import { WSClient } from '@/api/ws'
import type { TopicFilter } from '@/api/schemas'
import { useConnectionStore } from '@/state/connectionStore'
import { useMarketStore } from '@/state/marketStore'
import { useTradingStore } from '@/state/tradingStore'

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
        { name: 'market.candle', instrument_id: instrumentId },
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
  }

  stop(): void {
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
