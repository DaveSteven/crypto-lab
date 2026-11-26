import { create } from 'zustand'

/**
 * Price picked from the order book. Order Entry reads it and switches to a
 * LIMIT order draft; clicking never submits anything (docs/12 §10.1).
 */
interface OrderDraftState {
  pickedPrice: string | null
  pickNonce: number
  pickPrice: (price: string) => void
}

export const useOrderDraftStore = create<OrderDraftState>()((set) => ({
  pickedPrice: null,
  pickNonce: 0,
  pickPrice: (price) => set((state) => ({ pickedPrice: price, pickNonce: state.pickNonce + 1 })),
}))
