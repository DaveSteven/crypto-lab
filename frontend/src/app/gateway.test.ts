import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { RealtimeGateway } from './gateway'
import { WSClient } from '@/shared/api/ws'
import { useConnectionStore } from '@/app/connectionStore'
import { useTradingStore } from '@/features/trading/tradingStore'
import { useSessionStore } from '@/app/sessionStore'
import { useMarketStore } from '@/features/market/marketStore'

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
  const fakeRest = { snapshot: async () => snapshot } as unknown as import('@/shared/api/rest').RestClient
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

  test('candle interval switch subscribes the new channel and releases the previous one', async () => {
    const { gateway, socket } = makeGateway(snapshot)
    gateway.start('env-1', 'a-1', ['okx:SPOT:BTC/USDT'])
    readyAndAck(socket)
    await vi.waitFor(() => expect(useConnectionStore.getState().status).toBe('subscribed'))
    const sentTypes = () => socket.sent.map((raw) => JSON.parse(raw))
    const candle = (interval: string) => ({
      name: 'market.candle',
      instrument_id: 'okx:SPOT:BTC/USDT',
      interval,
    })

    gateway.setCandleInterval('okx:SPOT:BTC/USDT', '5m')
    expect(sentTypes().at(-1)).toMatchObject({ type: 'subscribe', topics: [candle('5m')] })
    gateway.setCandleInterval('okx:SPOT:BTC/USDT', '1h')
    const last = sentTypes().slice(-2)
    expect(last[0]).toMatchObject({ type: 'unsubscribe', topics: [candle('5m')] })
    expect(last[1]).toMatchObject({ type: 'subscribe', topics: [candle('1h')] })
    // Back to the resident 1m: release the dynamic one, never unsubscribe 1m.
    gateway.setCandleInterval('okx:SPOT:BTC/USDT', '1m')
    expect(sentTypes().at(-1)).toMatchObject({ type: 'unsubscribe', topics: [candle('1h')] })
    gateway.stop()
  })

  test('SUBSCRIPTION_LIMIT error is surfaced to the market store', async () => {
    const { gateway, socket } = makeGateway(snapshot)
    gateway.start('env-1', 'a-1', ['okx:SPOT:BTC/USDT'])
    readyAndAck(socket)
    socket.serverSend({ type: 'error', code: 'SUBSCRIPTION_LIMIT', message: 'candle channel limit reached (32)' })
    expect(useMarketStore.getState().candleSubscriptionError).toContain('limit')
    gateway.setCandleInterval('okx:SPOT:BTC/USDT', '5m')
    expect(useMarketStore.getState().candleSubscriptionError).toBeNull()
    gateway.stop()
  })
})
