import { create } from 'zustand'
import { barFromPayload, candleKey, mergeCandlePage, upsertCandle, type CandleBar } from '@/features/market/candles'
import type { MarketEvent, Ticker } from '@/shared/api/schemas'
import { Ticker as TickerSchema } from '@/shared/api/schemas'

export interface TickerView {
  ticker: Ticker
  eventTsMs: number
  receivedTsMs: number
}

export interface QualityView {
  status: string
  reason: string
  eventTsMs: number
}

export interface OrderBookView {
  bids: { price: string; quantity: string }[]
  asks: { price: string; quantity: string }[]
  sequenceId: string | null
  receivedTsMs: number
}

interface MarketState {
  candles: Record<string, CandleBar[]>
  tickers: Record<string, TickerView>
  quality: Record<string, QualityView>
  orderBooks: Record<string, OrderBookView>
  candleSubscriptionError: string | null
  setCandleSubscriptionError: (message: string | null) => void
  seedCandles: (instrumentId: string, interval: string, bars: CandleBar[]) => void
  applyMarketEvent: (message: MarketEvent) => void
  reset: () => void
}

export const useMarketStore = create<MarketState>()((set) => ({
  candles: {},
  tickers: {},
  quality: {},
  orderBooks: {},
  candleSubscriptionError: null,
  setCandleSubscriptionError: (message) => set({ candleSubscriptionError: message }),
  reset: () =>
    set({ candles: {}, tickers: {}, quality: {}, orderBooks: {}, candleSubscriptionError: null }),

  seedCandles: (instrumentId, interval, bars) =>
    set((state) => {
      const key = candleKey(instrumentId, interval)
      return {
        candles: {
          ...state.candles,
          [key]: mergeCandlePage(state.candles[key] ?? [], bars),
        },
      }
    }),

  applyMarketEvent: (message) =>
    set((state) => {
      const instrument = message.instrument_id ?? ''
      if (instrument === '') return state
      switch (message.type) {
        case 'market.candle': {
          const payload = message.payload as Record<string, unknown>
          const interval = message.interval ?? ''
          if (interval === '') return state
          const key = candleKey(instrument, interval)
          const bar = barFromPayload(message.event_id, payload as never)
          return {
            candles: {
              ...state.candles,
              [key]: upsertCandle(state.candles[key] ?? [], bar),
            },
          }
        }
        case 'market.ticker': {
          const parsed = TickerSchema.safeParse(message.payload)
          if (!parsed.success) return state
          return {
            tickers: {
              ...state.tickers,
              [instrument]: {
                ticker: parsed.data as Ticker,
                eventTsMs: message.event_ts_ms,
                receivedTsMs: message.published_ts_ms,
              },
            },
          }
        }
        case 'market.quality': {
          const payload = message.payload as { quality_status?: string; reason?: string }
          if (typeof payload.quality_status !== 'string') return state
          return {
            quality: {
              ...state.quality,
              [instrument]: {
                status: payload.quality_status,
                reason: payload.reason ?? '',
                eventTsMs: message.event_ts_ms,
              },
            },
          }
        }
        case 'market.order_book': {
          const payload = message.payload as {
            bids?: { price: string; quantity: string }[]
            asks?: { price: string; quantity: string }[]
            sequence_id?: string | null
            received_ts_ms?: number
          }
          return {
            orderBooks: {
              ...state.orderBooks,
              [instrument]: {
                bids: payload.bids ?? [],
                asks: payload.asks ?? [],
                sequenceId: payload.sequence_id ?? null,
                receivedTsMs: payload.received_ts_ms ?? message.event_ts_ms,
              },
            },
          }
        }
        default:
          return state
      }
    }),
}))
