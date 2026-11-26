import { create } from 'zustand'

/** Which order (and optionally which fill) the detail drawer shows. */
interface DetailState {
  orderId: string | null
  executionId: string | null
  open: (orderId: string, executionId?: string) => void
  close: () => void
}

export const useDetailStore = create<DetailState>()((set) => ({
  orderId: null,
  executionId: null,
  open: (orderId, executionId) => set({ orderId, executionId: executionId ?? null }),
  close: () => set({ orderId: null, executionId: null }),
}))
