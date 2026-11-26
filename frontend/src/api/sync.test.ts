import { describe, expect, test, vi } from 'vitest'
import { TradingStateSync } from './sync'
import type { Snapshot } from './schemas'
import type { RestClient } from './rest'
import { WSClient } from './ws'

class FakeSocket {
  readyState = 1
  sent: string[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: unknown }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  send(data: string) {
    this.sent.push(data)
  }
  close() {
    this.onclose?.()
  }
  serverSend(value: unknown) {
    this.onmessage?.({ data: JSON.stringify(value) })
  }
}

function tradingEvent(overrides: Record<string, unknown>) {
  return {
    protocol_version: '1.0.0',
    environment_id: 'env-1',
    stream_id: 'stream-a',
    event_id: 'e-1',
    event_ts_ms: 1_000,
    published_ts_ms: 1_000,
    stream_sequence: 1,
    payload: {},
    type: 'orders',
    ...overrides,
  }
}

function makeSnapshot(stateVersion: number): Snapshot {
  return {
    environment_id: 'env-1',
    account_id: 'a-1',
    state_version: stateVersion,
    account: {},
    balances: [],
    orders: [],
    executions: [],
    positions: [],
  }
}

function buildSync(snapshot: Snapshot) {
  const socket = new FakeSocket()
  const client = new WSClient({ url: 'ws://test/ws', socketFactory: () => socket })
  const appliedSnapshots: Snapshot[] = []
  const appliedEvents: string[] = []
  const rest = {
    snapshot: vi.fn().mockResolvedValue(snapshot),
  } as unknown as RestClient
  const sync = new TradingStateSync(client, rest, 'env-1', 'a-1', {
    applySnapshot: (value) => appliedSnapshots.push(value),
    applyEvent: (event) => appliedEvents.push(`${event.type}:${event.event_id}`),
  })
  client.connect()
  socket.onopen?.()
  socket.serverSend({
    protocol_version: '1.0.0',
    type: 'session.ready',
    environment_id: 'env-1',
    stream_id: 'stream-a',
    stream_sequence: 0,
  })
  return { sync, socket, appliedSnapshots, appliedEvents }
}

describe('TradingStateSync', () => {
  test('buffers during snapshot fetch, drops stale versions, applies the rest in order', async () => {
    const { sync, socket, appliedSnapshots, appliedEvents } = buildSync(makeSnapshot(5))

    // First run: full resync with an empty buffer.
    await sync.resync()
    expect(appliedSnapshots).toHaveLength(1)

    // Simulate replayed events arriving (e.g. after reconnect) while a
    // resync snapshot request is in flight.
    const secondResync = sync.resync()
    socket.serverSend(tradingEvent({ event_id: 'old', state_version: 5, event_index: 1 }))
    socket.serverSend(tradingEvent({ event_id: 'new-2', state_version: 6, event_index: 2 }))
    socket.serverSend(tradingEvent({ event_id: 'new-1', state_version: 6, event_index: 1 }))
    await secondResync

    expect(appliedSnapshots).toHaveLength(2)
    // state_version 5 equals the snapshot version -> dropped; 6 applied in
    // event_index order.
    expect(appliedEvents).toEqual(['orders:new-1', 'orders:new-2'])
  })

  test('live events dedupe by event id and ignore pre-snapshot versions', async () => {
    const { sync, socket, appliedEvents } = buildSync(makeSnapshot(5))
    await sync.resync()
    socket.serverSend(tradingEvent({ event_id: 'live-1', state_version: 6, event_index: 1 }))
    socket.serverSend(tradingEvent({ event_id: 'live-1', state_version: 6, event_index: 1 }))
    socket.serverSend(tradingEvent({ event_id: 'stale', state_version: 4, event_index: 1 }))
    expect(appliedEvents).toEqual(['orders:live-1'])
  })

  test('resync required triggers a fresh snapshot flow', async () => {
    const { sync, socket, appliedSnapshots } = buildSync(makeSnapshot(9))
    socket.serverSend({ type: 'resync.required', reason: 'slow consumer' })
    await vi.waitFor(() => {
      expect(appliedSnapshots).toHaveLength(1)
    })
    expect(sync).toBeInstanceOf(TradingStateSync)
  })
})
