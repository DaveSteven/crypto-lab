import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export const DEFAULT_INSTRUMENT = 'okx:SPOT:BTC/USDT'

export interface InstrumentParts {
  exchange: string
  marketType: string
  base: string
  quote: string
  symbol: string
}

/** `okx:SPOT:BTC/USDT` → parts. Falls back to the raw id for unexpected shapes. */
export function splitInstrument(instrumentId: string): InstrumentParts {
  const [exchange = '', marketType = '', symbol = instrumentId] = instrumentId.split(':')
  const [base = symbol, quote = ''] = symbol.split('/')
  return { exchange, marketType, base, quote, symbol }
}

interface InstrumentState {
  instrumentId: string
  setInstrument: (instrumentId: string) => void
}

/** The instrument shown by the Trading workspace (chart, order book, order entry). */
export const useInstrumentStore = create<InstrumentState>()(
  persist(
    (set) => ({
      instrumentId: DEFAULT_INSTRUMENT,
      setInstrument: (instrumentId) => set({ instrumentId }),
    }),
    { name: 'crypto-lab.instrument' },
  ),
)

export function useInstrument(): InstrumentParts & { instrumentId: string } {
  const instrumentId = useInstrumentStore((state) => state.instrumentId)
  return { instrumentId, ...splitInstrument(instrumentId) }
}
