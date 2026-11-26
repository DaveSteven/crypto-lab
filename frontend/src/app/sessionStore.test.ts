import { beforeEach, describe, expect, test } from 'vitest'
import { useSessionStore } from './sessionStore'

beforeEach(() => {
  useSessionStore.getState().clearSession()
})

describe('sessionStore', () => {
  test('persists the session across store instances via localStorage', () => {
    useSessionStore.getState().setSession({ environmentId: 'env-1', accountId: 'a-1' })
    const raw = localStorage.getItem('crypto-lab.session')
    expect(raw).not.toBeNull()
    expect(JSON.parse(raw as string).state.session).toEqual({
      environmentId: 'env-1',
      accountId: 'a-1',
    })
    useSessionStore.getState().clearSession()
    expect(useSessionStore.getState().session).toBeNull()
  })
})
