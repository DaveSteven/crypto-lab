import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { RealtimeGateway } from './gateway'
import { WSClient } from '@/api/ws'
import { useConnectionStore } from '@/state/connectionStore'
import { useTradingStore } from '@/state/tradingStore'
import { useSessionStore } from '@/state/sessionStore'

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

const createdClients: WSClient[] = []

function makeGateway(snapshot: object) {
  const socket = new FakeSocket()
  const fakeRest = { snapshot: async () => snapshot } as unknown as import('@/api/rest').RestClient
  const gateway = new RealtimeGateway({
    createRest: () => fakeRest,
    createClient: (url: string) => {
      const client = new WSClient({ url, socketFactory: () => socket })
      createdClients.push(client)
      return client
    },
  })
  return { gateway, socket }
}

function readyAndAck(socket: FakeSocket) {
  socket.onopen?.()
  socket.serverSend({
    protocol_version: '1.0.0',
    type: 'session.ready',
    environment_id: 'env-1',
    stream_id: 'stream-a',
    stream_sequence: 0,
  })
  const subscribeRequest = JSON.parse(socket.sent[0])
  socket.serverSend({
    type: 'subscription.ack',
    request_id: subscribeRequest.request_id,
    replayed: 0,
  })
  return subscribeRequest
}

const snapshot = {
  environment_id: 'env-1',
  account_id: 'a-1',
  state_version: 4,
  account: {},
  balances: [{ asset: 'USDT', available: '10000', locked: '0' }],
  orders: [],
  executions: [],
  positions: [],
}

beforeEach(() => {
  createdClients.length = 0
  useConnectionStore.getState().update({
    status: 'idle',
    streamId: null,
    lastEventTsMs: null,
    resyncReason: null,
  })
  useTradingStore.getState().reset()
  useSessionStore.getState().clearSession()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('RealtimeGateway', () => {
  test('drives connection status into the connection store', async () => {
    const { gateway, socket } = makeGateway(snapshot)
    gateway.start('env-1', 'a-1')
    expect(useConnectionStore.getState().status).toBe('connecting')
    readyAndAck(socket)
    await vi.waitFor(() => {
      expect(useConnectionStore.getState().status).toBe('subscribed')
    })
    gateway.stop()
    expect(useConnectionStore.getState().status).toBe('closed')
  })

  test('applies the REST snapshot into the trading store after subscribe', async () => {
    const { gateway, socket } = makeGateway(snapshot)
    gateway.start('env-1', 'a-1')
    readyAndAck(socket)
    await vi.waitFor(() => {
      expect(useTradingStore.getState().stateVersion).toBe(4)
    })
    expect(useTradingStore.getState().balances).toEqual([
      { asset: 'USDT', available: '10000', locked: '0' },
    ])
    gateway.stop()
  })

  test('subscribes trading topics scoped to the account and market topics per instrument', () => {
    const { gateway, socket } = makeGateway(snapshot)
    gateway.start('env-1', 'a-1', ['okx:SPOT:BTC/USDT'])
    const subscribeRequest = readyAndAck(socket)
    const topics = subscribeRequest.topics as { name: string; account_id?: string; instrument_id?: string }[]
    const names = topics.map((topic) => topic.name)
    expect(names).toEqual(
      expect.arrayContaining([
        'orders',
        'balances',
        'executions',
        'positions',
        'market.ticker',
        'market.candle',
        'market.quality',
      ]),
    )
    expect(topics.find((topic) => topic.name === 'orders')?.account_id).toBe('a-1')
    expect(topics.find((topic) => topic.name === 'market.ticker')?.instrument_id).toBe(
      'okx:SPOT:BTC/USDT',
    )
    gateway.stop()
  })

  test('restarting for the same session is idempotent', () => {
    const { gateway } = makeGateway(snapshot)
    gateway.start('env-1', 'a-1')
    gateway.start('env-1', 'a-1')
    expect(createdClients).toHaveLength(1)
    gateway.start('env-2', 'a-1')
    expect(createdClients).toHaveLength(2)
    gateway.stop()
  })
})
