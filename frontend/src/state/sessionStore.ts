import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface Session {
  environmentId: string
  accountId: string
}

interface SessionState {
  session: Session | null
  setSession: (session: Session) => void
  clearSession: () => void
}

/**
 * Local simulation session (environment + account selection). Persisted to
 * localStorage so a refresh keeps the same environment; the authoritative
 * state is always re-fetched from REST after connect (docs/10 §8.1).
 */
export const useSessionStore = create<SessionState>()(
  persist(
    (set) => ({
      session: null,
      setSession: (session) => set({ session }),
      clearSession: () => set({ session: null }),
    }),
    { name: 'crypto-lab.session' },
  ),
)
