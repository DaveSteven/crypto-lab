import { create } from 'zustand'

/**
 * Price picked from the order book. Order Entry reads it and switches to a
 * LIMIT order draft; clicking never submits anything (docs/12 §10.1).
 */
interface OrderDraftState {
  pickedPrice: string | null
  pickNonce: number
  pickPrice: (price: string) => void
  plannedOrder: PlannedOrder | null
  planNonce: number
  applyPlan: (plan: PlannedOrder) => void
  clearPlan: () => void
}

interface PlannedOrder {
  instrumentId: string
  quantity: string
  limitPrice: string
  journalId: string
  journalVersion: number
}

export const useOrderDraftStore = create<OrderDraftState>()((set) => ({
  pickedPrice: null,
  pickNonce: 0,
  pickPrice: (price) => set((state) => ({ pickedPrice: price, pickNonce: state.pickNonce + 1 })),
  plannedOrder: null,
  planNonce: 0,
  applyPlan: (plannedOrder) => set((state) => ({ plannedOrder, planNonce: state.planNonce + 1 })),
  clearPlan: () => set({ plannedOrder: null }),
}))
