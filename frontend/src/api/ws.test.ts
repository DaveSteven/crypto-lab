import { describe, expect, test, vi } from 'vitest'
import { WSClient, type WSStatus } from './ws'

type Handler = (event: { data: unknown }) => void

class FakeSocket {
  readyState = 1
  sent: string[] = []
  closed = false
  onopen: (() => void) | null = null
  onmessage: Handler | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null

  send(data: string) {
    this.sent.push(data)
  }

  close() {
    this.closed = true
    this.onclose?.()
  }

  /** Simulate the server sending a raw JSON text frame. */
  serverSend(value: unknown) {
    this.onmessage?.({ data: JSON.stringify(value) })
  }
}

const BASE_ENVELOPE = {
  protocol_version: '1.0.0',
  environment_id: 'env-1',
  stream_id: 'stream-a',
  event_id: 'e-1',
  event_ts_ms: 1_000,
  published_ts_ms: 1_000,
  payload: {},
}

function tradingEnvelope(overrides: Record<string, unknown>) {
  return {
    ...BASE_ENVELOPE,
    type: 'orders',
    stream_sequence: 1,
    delivery_sequence: 1,
    ...overrides,
  }
}

function connectClient(callbacks: { statuses?: WSStatus[]; resyncs?: string[] } = {}) {
  const socket = new FakeSocket()
  const client = new WSClient({
    url: 'ws://test/ws',
    socketFactory: () => socket,
    backoffMs: () => 0,
    callbacks: {
      onStatus: (status) => callbacks.statuses?.push(status),
      onResyncRequired: (reason) => callbacks.resyncs?.push(reason),
    },
  })
  client.connect()
  socket.onopen?.()
  return { client, socket }
}

function sessionReady(socket: FakeSocket, streamId = 'stream-a', sequence = 0) {
  socket.serverSend({
    protocol_version: '1.0.0',
    type: 'session.ready',
    environment_id: 'env-1',
    stream_id: streamId,
    stream_sequence: sequence,
  })
}

describe('WSClient', () => {
  test('session.ready flips to ready and subscribe resumes from the cursor', async () => {
    const { client, socket } = connectClient()
    sessionReady(socket, 'stream-a', 42)
    expect(client.status).toBe('ready')
    const subscribePromise = client.subscribe([{ name: 'orders', account_id: 'a-1' }])
    const request = JSON.parse(socket.sent[0])
    expect(request.type).toBe('subscribe')
    expect(request.resume_from).toEqual({ stream_id: 'stream-a', stream_sequence: 42 })
    socket.serverSend({ type: 'subscription.ack', request_id: request.request_id, replayed: 3 })
    await expect(subscribePromise).resolves.toEqual({ replayed: 3 })
    expect(client.status).toBe('subscribed')
    client.stop()
  })

  test('heartbeat gets answered with pong echoing the heartbeat id', () => {
    const { client, socket } = connectClient()
    sessionReady(socket)
    socket.serverSend({ type: 'heartbeat', heartbeat_id: 'hb-7' })
    const reply = JSON.parse(socket.sent.at(-1) ?? '{}')
    expect(reply).toEqual({ type: 'pong', heartbeat_id: 'hb-7' })
    client.stop()
  })

  test('delivery_sequence gaps trigger exactly one resync request', () => {
    const statuses: WSStatus[] = []
    const resyncs: string[] = []
    const { client, socket } = connectClient({ statuses, resyncs })
    sessionReady(socket)
    const seen: string[] = []
    client.callbacks.onMessage = (message) => seen.push(message.type)

    socket.serverSend(tradingEnvelope({ event_id: 'e-1', delivery_sequence: 1 }))
    socket.serverSend(tradingEnvelope({ event_id: 'e-2', delivery_sequence: 2 }))
    socket.serverSend(tradingEnvelope({ event_id: 'e-3', delivery_sequence: 5 }))

    expect(seen).toEqual(['orders', 'orders'])
    expect(resyncs).toHaveLength(1)
    expect(resyncs[0]).toContain('delivery_sequence gap')
    expect(client.status).toBe('resync-required')
    client.stop()
  })

  test('stream_sequence gaps are normal and never trigger a resync', () => {
    const resyncs: string[] = []
    const { client, socket } = connectClient({ resyncs })
    sessionReady(socket)
    socket.serverSend({
      ...BASE_ENVELOPE,
      type: 'market.ticker',
      stream_sequence: 100,
      payload: { bid: '100' },
    })
    socket.serverSend({
      ...BASE_ENVELOPE,
      type: 'market.ticker',
      stream_sequence: 500,
      event_id: 'e-2',
      payload: { bid: '101' },
    })
    expect(resyncs).toHaveLength(0)
    expect(client.status).toBe('ready')
    client.stop()
  })

  test('duplicate event ids are delivered once', () => {
    const { client, socket } = connectClient()
    sessionReady(socket)
    const seen: string[] = []
    client.callbacks.onMessage = (message) => {
      if (!('event_id' in message)) return
      seen.push(message.event_id)
    }
    socket.serverSend(tradingEnvelope({ event_id: 'same' }))
    socket.serverSend(tradingEnvelope({ event_id: 'same' }))
    expect(seen).toEqual(['same'])
    client.stop()
  })

  test('a new stream_id invalidates the cursor and requests resync', () => {
    const resyncs: string[] = []
    const { client, socket } = connectClient({ resyncs })
    sessionReady(socket, 'stream-a', 10)
    socket.serverSend(tradingEnvelope({ event_id: 'e-1', stream_sequence: 11 }))
    sessionReady(socket, 'stream-b', 1)
    expect(resyncs.some((reason) => reason.includes('stream_id changed'))).toBe(true)
    expect(client.streamId).toBe('stream-b')
    expect(client.lastStreamSequence).toBe(1)
    client.stop()
  })

  test('reconnects with backoff after a close and resumes', async () => {
    vi.useFakeTimers()
    const sockets: FakeSocket[] = []
    const client = new WSClient({
      url: 'ws://test/ws',
      socketFactory: () => {
        const socket = new FakeSocket()
        sockets.push(socket)
        return socket
      },
      backoffMs: () => 5,
    })
    client.connect()
    sockets[0].onopen?.()
    sessionReady(sockets[0], 'stream-a', 20)
    client.subscribe([{ name: 'orders', account_id: 'a-1' }])
    sockets[0].onclose?.()

    await vi.advanceTimersByTimeAsync(10)
    expect(sockets).toHaveLength(2)
    expect(client.status).toBe('connecting')
    sessionReady(sockets[1], 'stream-a', 25)
    const subscribeRequest = JSON.parse(sockets[1].sent[0])
    expect(subscribeRequest.resume_from).toEqual({ stream_id: 'stream-a', stream_sequence: 20 })
    client.stop()
    vi.useRealTimers()
  })

  test('server resync.required resets the delivery cursor and notifies', () => {
    const resyncs: string[] = []
    const { client, socket } = connectClient({ resyncs })
    sessionReady(socket)
    socket.serverSend(tradingEnvelope({ event_id: 'e-1', delivery_sequence: 3 }))
    socket.serverSend({ type: 'resync.required', reason: 'slow consumer' })
    expect(resyncs).toEqual(['slow consumer'])
    // After a resync the next delivery sequence starts fresh.
    socket.serverSend(tradingEnvelope({ event_id: 'e-2', delivery_sequence: 1 }))
    expect(client.status).toBe('resync-required')
    client.stop()
  })
})
