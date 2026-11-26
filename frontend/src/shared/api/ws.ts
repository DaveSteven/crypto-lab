import type { MarketEvent, ResumeFrom, ServerMessage, TopicFilter, TradingEvent } from './schemas'
import { ServerMessage as ServerMessageSchema } from './schemas'

export type WSStatus =
  | 'idle'
  | 'connecting'
  | 'ready'
  | 'subscribed'
  | 'resync-required'
  | 'closed'

type AnySocket = {
  send: (data: string) => void
  close: () => void
  readyState: number
}

export type Unsubscribe = () => void

export interface WSClientOptions {
  url: string
  /** Defaults to the browser WebSocket with the crypto-lab.v1 subprotocol. */
  socketFactory?: (url: string) => AnySocket
  backoffMs?: (attempt: number) => number
}

/**
 * Client for the crypto-lab.v1 protocol (docs/10).
 *
 * Ordering contract implemented here:
 * - stream_sequence gaps are normal (server-side filtering/coalescing) and
 *   never trigger a resync;
 * - delivery_sequence gaps on trading topics mean this connection lost
 *   events and MUST trigger a REST resync;
 * - session.ready with a new stream_id (process restart) invalidates the
 *   resume cursor and forces a full resync.
 */
export class WSClient {
  status: WSStatus = 'idle'
  streamId: string | null = null
  lastStreamSequence = 0
  lastDeliverySequence: number | null = null

  private readonly url: string
  private readonly socketFactory: (url: string) => AnySocket
  private readonly backoffMs: (attempt: number) => number
  private readonly statusListeners = new Set<(status: WSStatus) => void>()
  private readonly messageListeners = new Set<(message: ServerMessage) => void>()
  private readonly resyncListeners = new Set<(reason: string) => void>()
  private socket: AnySocket | null = null
  private requestCounter = 0
  private readonly pendingRequests = new Map<string, (ack: { replayed?: number }) => void>()
  private reconnectAttempt = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private stopped = false
  private subscriptions: TopicFilter[] = []
  private readonly seenEventIds = new Set<string>()
  private static readonly SEEN_EVENT_LIMIT = 5_000

  constructor(options: WSClientOptions) {
    this.url = options.url
    this.socketFactory =
      options.socketFactory ?? ((socketUrl) => new WebSocket(socketUrl, ['crypto-lab.v1']))
    this.backoffMs = options.backoffMs ?? ((attempt) => Math.min(1_000 * 2 ** attempt, 30_000))
  }

  onStatus(listener: (status: WSStatus) => void): Unsubscribe {
    this.statusListeners.add(listener)
    return () => this.statusListeners.delete(listener)
  }

  /** Business messages after envelope validation and ordering checks. */
  onMessage(listener: (message: ServerMessage) => void): Unsubscribe {
    this.messageListeners.add(listener)
    return () => this.messageListeners.delete(listener)
  }

  /** Trading delivery gap or explicit resync.required from the server. */
  onResync(listener: (reason: string) => void): Unsubscribe {
    this.resyncListeners.add(listener)
    return () => this.resyncListeners.delete(listener)
  }

  /** Set the topics (re)subscribed automatically on every session.ready. */
  setTopics(topics: TopicFilter[]): void {
    this.subscriptions = topics
  }

  connect(): void {
    this.stopped = false
    this.setStatus('connecting')
    this.openSocket()
  }

  /** Subscribe (or resubscribe after reconnect) with an optional resume cursor. */
  subscribe(topics: TopicFilter[], resumeFrom?: ResumeFrom): Promise<{ replayed?: number }> {
    this.subscriptions = topics
    const cursor = resumeFrom ?? this.resumeCursor()
    const requestId = this.nextRequestId()
    const promise = new Promise<{ replayed?: number }>((resolve) => {
      this.pendingRequests.set(requestId, resolve)
    })
    this.send({
      type: 'subscribe',
      request_id: requestId,
      topics,
      ...(cursor ? { resume_from: cursor } : {}),
    })
    return promise
  }

  unsubscribe(topics: TopicFilter[]): void {
    this.subscriptions = this.subscriptions.filter(
      (topic) => !topics.some((removed) => filtersEqual(topic, removed)),
    )
    this.send({ type: 'unsubscribe', request_id: this.nextRequestId(), topics })
  }

  ping(): void {
    this.send({ type: 'ping', request_id: this.nextRequestId() })
  }

  /** Reply to the server heartbeat (docs/10 §4.2). */
  sendHeartbeatReply(heartbeatId: string): void {
    this.send({ type: 'pong', heartbeat_id: heartbeatId })
  }

  stop(): void {
    this.stopped = true
    if (this.reconnectTimer !== null) clearTimeout(this.reconnectTimer)
    this.socket?.close()
    this.socket = null
    this.setStatus('closed')
  }

  private openSocket(): void {
    const socket = this.socketFactory(this.url)
    this.socket = socket
    // The browser WebSocket API delivers lifecycle events on the instance;
    // tests inject a stub with the same surface.
    const real = socket as AnySocket & {
      onopen: (() => void) | null
      onmessage: ((event: { data: unknown }) => void) | null
      onclose: (() => void) | null
      onerror: (() => void) | null
    }
    real.onopen = () => {
      // session.ready follows the accept; status flips there.
    }
    real.onmessage = (event) => {
      this.handleRawMessage(event.data)
    }
    real.onclose = () => {
      this.socket = null
      if (this.stopped) return
      this.scheduleReconnect()
    }
    real.onerror = () => {
      // close follows; nothing to do here.
    }
  }

  private scheduleReconnect(): void {
    this.setStatus('closed')
    const delay = this.backoffMs(this.reconnectAttempt)
    this.reconnectAttempt += 1
    this.reconnectTimer = setTimeout(() => {
      this.setStatus('connecting')
      this.openSocket()
    }, delay)
  }

  private handleRawMessage(data: unknown): void {
    if (typeof data !== 'string') return
    let parsed: unknown
    try {
      parsed = JSON.parse(data)
    } catch {
      return
    }
    const message = ServerMessageSchema.safeParse(parsed)
    if (!message.success) return
    const value = message.data

    switch (value.type) {
      case 'session.ready': {
        if (this.streamId !== null && this.streamId !== value.stream_id) {
          // Server process restarted: the replay cursor is meaningless.
          this.lastDeliverySequence = null
          this.seenEventIds.clear()
          this.notifyResync('stream_id changed: server restarted')
          this.setStatus('resync-required')
          this.lastStreamSequence = value.stream_sequence
        } else if (this.streamId === null) {
          // First session on this connection: start the cursor at the head.
          this.lastStreamSequence = value.stream_sequence
        }
        // Same stream_id after a reconnect: keep the last processed
        // sequence so the resume replays everything missed in between.
        this.streamId = value.stream_id
        this.reconnectAttempt = 0
        this.setStatus('ready')
        void this.subscribeWithResume()
        return
      }
      case 'subscription.ack': {
        this.setStatus('subscribed')
        this.pendingRequests.get(value.request_id)?.({ replayed: value.replayed })
        this.pendingRequests.delete(value.request_id)
        return
      }
      case 'pong': {
        this.pendingRequests.get(value.request_id)?.({})
        this.pendingRequests.delete(value.request_id)
        return
      }
      case 'heartbeat': {
        this.sendHeartbeatReply(value.heartbeat_id)
        return
      }
      case 'resync.required': {
        this.lastDeliverySequence = null
        this.setStatus('resync-required')
        this.notifyResync(value.reason)
        return
      }
      case 'error': {
        for (const listener of this.messageListeners) listener(value)
        return
      }
      default: {
        this.handleBusinessMessage(value)
      }
    }
  }

  private handleBusinessMessage(value: MarketEvent | TradingEvent): void {
    const delivery = value.delivery_sequence
    if (typeof delivery === 'number') {
      if (
        this.lastDeliverySequence !== null &&
        delivery !== this.lastDeliverySequence + 1
      ) {
        this.lastDeliverySequence = delivery
        this.setStatus('resync-required')
        this.notifyResync(`delivery_sequence gap: ${this.lastDeliverySequence} -> ${delivery}`)
        return
      }
      this.lastDeliverySequence = delivery
    }
    if (this.seenEventIds.has(value.event_id)) return
    this.seenEventIds.add(value.event_id)
    if (this.seenEventIds.size > WSClient.SEEN_EVENT_LIMIT) {
      const oldest = this.seenEventIds.values().next().value
      if (oldest !== undefined) this.seenEventIds.delete(oldest)
    }
    this.lastStreamSequence = Math.max(this.lastStreamSequence, value.stream_sequence)
    for (const listener of this.messageListeners) listener(value)
  }

  private notifyResync(reason: string): void {
    for (const listener of this.resyncListeners) listener(reason)
  }

  private async subscribeWithResume(): Promise<void> {
    if (this.subscriptions.length === 0) return
    await this.subscribe(this.subscriptions)
  }

  private resumeCursor(): ResumeFrom | undefined {
    if (this.streamId === null || this.lastStreamSequence <= 0) return undefined
    return { stream_id: this.streamId, stream_sequence: this.lastStreamSequence }
  }

  private setStatus(status: WSStatus): void {
    this.status = status
    for (const listener of this.statusListeners) listener(status)
  }

  private nextRequestId(): string {
    this.requestCounter += 1
    return `req-${this.requestCounter}`
  }

  private send(message: Record<string, unknown>): void {
    if (this.socket === null) return
    this.socket.send(JSON.stringify(message))
  }
}

function filtersEqual(a: TopicFilter, b: TopicFilter): boolean {
  return (
    a.name === b.name &&
    a.instrument_id === b.instrument_id &&
    a.account_id === b.account_id &&
    a.interval === b.interval
  )
}
