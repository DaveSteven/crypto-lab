import type { RestClient } from './rest'
import type { WSClient } from './ws'
import type { Snapshot, TradingEvent } from './schemas'

export interface TradingStateSink {
  /** Replace the whole state with the authoritative REST snapshot. */
  applySnapshot: (snapshot: Snapshot) => void
  /** Apply one committed trading event (idempotent per event_id). */
  applyEvent: (event: TradingEvent) => void
}

/**
 * docs/10 §8.1 client-side consistency flow:
 *
 * 1. buffer trading events arriving over WS,
 * 2. fetch the REST snapshot (authoritative state_version V),
 * 3. drop buffered events with state_version <= V,
 * 4. apply the snapshot, then remaining events ordered by
 *    (state_version, event_index),
 * 5. afterwards apply live trading events as they arrive, deduplicating
 *    by event_id.
 */
export class TradingStateSync {
  private readonly rest: RestClient
  private readonly environmentId: string
  private readonly accountId: string
  private readonly sink: TradingStateSink
  private readonly seenEventIds = new Set<string>()
  private buffering = false
  private buffer: TradingEvent[] = []
  private lastStateVersion = 0

  constructor(
    client: WSClient,
    rest: RestClient,
    environmentId: string,
    accountId: string,
    sink: TradingStateSink,
  ) {
    this.rest = rest
    this.environmentId = environmentId
    this.accountId = accountId
    this.sink = sink
    client.onMessage((message) => {
      if (
        message.type === 'orders' ||
        message.type === 'balances' ||
        message.type === 'executions' ||
        message.type === 'positions'
      ) {
        this.handleTradingEvent(message)
      }
    })
    client.onResync(() => {
      void this.resync()
    })
  }

  /** Run the full resync flow; safe to call again at any time. */
  async resync(): Promise<void> {
    this.buffering = true
    this.buffer = []
    try {
      const snapshot = await this.rest.snapshot(this.environmentId, this.accountId)
      this.lastStateVersion = snapshot.state_version
      const remaining = this.buffer
        .filter((event) => (event.state_version ?? 0) > snapshot.state_version)
        .filter((event) => !this.seenEventIds.has(event.event_id))
      this.seenEventIds.clear()
      this.sink.applySnapshot(snapshot)
      remaining.sort(compareTradingEvents)
      for (const event of remaining) {
        this.applyCommitted(event)
      }
    } finally {
      this.buffering = false
      this.buffer = []
    }
  }

  private handleTradingEvent(event: TradingEvent): void {
    if (this.buffering) {
      this.buffer.push(event)
      return
    }
    if ((event.state_version ?? 0) < this.lastStateVersion) {
      // Stale replay from before the current snapshot.
      return
    }
    if (this.seenEventIds.has(event.event_id)) return
    this.applyCommitted(event)
  }

  private applyCommitted(event: TradingEvent): void {
    this.seenEventIds.add(event.event_id)
    this.lastStateVersion = Math.max(this.lastStateVersion, event.state_version ?? 0)
    this.sink.applyEvent(event)
  }
}

function compareTradingEvents(a: TradingEvent, b: TradingEvent): number {
  const versionA = a.state_version ?? 0
  const versionB = b.state_version ?? 0
  if (versionA !== versionB) return versionA - versionB
  return (a.event_index ?? 0) - (b.event_index ?? 0)
}
