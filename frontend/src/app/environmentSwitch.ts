import type { QueryClient } from '@tanstack/react-query'
import { RestClient } from '@/shared/api/rest'
import { gateway } from '@/app/gateway'
import { useSessionStore } from '@/app/sessionStore'
import { useTradingStore } from '@/features/trading/tradingStore'
import { useMarketStore } from '@/features/market/marketStore'
import { useDetailStore } from '@/features/trading/detailStore'

const rest = new RestClient()

/**
 * Environment switching (docs/12 §17.5). Order matters: drop the old
 * subscription and every piece of old-environment state first, then publish the
 * new session. The gate then subscribes and loads the authoritative snapshot;
 * trading stays disabled until that snapshot is applied (`tradingStore.synced`).
 * Old orders, balances and positions are never shown under the new environment.
 */
export async function switchEnvironment(
  environmentId: string,
  queryClient: QueryClient,
): Promise<void> {
  const current = useSessionStore.getState().session
  if (current?.environmentId === environmentId) return
  const accounts = await rest.listAccounts(environmentId, 1)
  const account = accounts[0]
  if (account === undefined) throw new Error('该环境下没有模拟账户，无法切换。')
  enterSession(environmentId, account.account_id, queryClient)
}

/** Shared by switch and create: tear down the old environment, then enter the new one. */
export function enterSession(environmentId: string, accountId: string, queryClient: QueryClient): void {
  gateway.stop()
  useTradingStore.getState().reset()
  useMarketStore.getState().reset()
  useDetailStore.getState().close()
  queryClient.removeQueries()
  useSessionStore.getState().setSession({ environmentId, accountId })
}
