import { useEffect, useState, type FormEvent } from 'react'
import { useSessionStore } from '@/app/sessionStore'
import { useTradingStore } from '@/features/trading/tradingStore'
import { useMarketStore } from '@/features/market/marketStore'
import { gateway } from '@/app/gateway'
import { RestClient } from '@/shared/api/rest'

const rest = new RestClient()

/** Used only when the instrument list cannot be fetched; the documented single-pair default. */
const FALLBACK_INSTRUMENTS = ['okx:SPOT:BTC/USDT']

/**
 * Session bootstrap: create (or reuse) the local simulation environment and
 * paper account, then start the shared realtime gateway. Order intent only —
 * the backend decides every execution outcome.
 */
export function EnvironmentGate({ children }: { children: React.ReactNode }) {
  const session = useSessionStore((state) => state.session)
  const setSession = useSessionStore((state) => state.setSession)
  const clearSession = useSessionStore((state) => state.clearSession)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [form, setForm] = useState({
    environmentName: '本地模拟环境',
    accountName: 'Paper Account',
    initialAmount: '10000',
  })

  const active = session !== null

  useEffect(() => {
    if (!active || session === null) return
    // Subscribe to every instrument the backend actually feeds (not to whatever
    // page is open) so Overview valuation never depends on the Trading page.
    let cancelled = false
    void rest
      .marketInstruments()
      .then((result) => result.items.map((item) => item.instrument_id))
      .catch(() => FALLBACK_INSTRUMENTS)
      .then((instruments) => {
        if (!cancelled) gateway.start(session.environmentId, session.accountId, instruments)
      })
    return () => {
      cancelled = true
      gateway.stop()
    }
  }, [active, session])

  if (active && session !== null) {
    return (
      <>
        {children}
        <button
          type="button"
          className="text-xs text-muted-foreground underline"
          onClick={() => {
            gateway.stop()
            useTradingStore.getState().reset()
            useMarketStore.getState().reset()
            clearSession()
          }}
        >
          重置会话
        </button>
      </>
    )
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (submitting) return
    setSubmitting(true)
    setError(null)
    try {
      const environment = await rest.createEnvironment(form.environmentName)
      const account = await rest.createAccount(environment.environment_id, {
        exchange_id: 'okx',
        name: form.accountName,
        initial_asset: 'USDT',
        initial_amount: form.initialAmount,
      })
      setSession({ environmentId: environment.environment_id, accountId: account.account_id })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section aria-labelledby="bootstrap-title" className="mx-auto max-w-md space-y-4">
      <h1 id="bootstrap-title" className="text-lg font-semibold">
        初始化模拟交易环境
      </h1>
      <p className="text-sm text-muted-foreground">
        创建一个隔离的模拟环境与虚拟资金账户。所有资金均为模拟数据，不会产生真实订单。
      </p>
      <form className="space-y-3" onSubmit={handleSubmit}>
        <label className="block text-sm">
          环境名称
          <input
            className="mt-1 w-full rounded-md border bg-transparent px-3 py-2 text-sm"
            value={form.environmentName}
            onChange={(event) => setForm({ ...form, environmentName: event.target.value })}
            required
          />
        </label>
        <label className="block text-sm">
          账户名称
          <input
            className="mt-1 w-full rounded-md border bg-transparent px-3 py-2 text-sm"
            value={form.accountName}
            onChange={(event) => setForm({ ...form, accountName: event.target.value })}
            required
          />
        </label>
        <label className="block text-sm">
          初始虚拟资金（USDT）
          <input
            className="mt-1 w-full rounded-md border bg-transparent px-3 py-2 text-sm"
            value={form.initialAmount}
            onChange={(event) => setForm({ ...form, initialAmount: event.target.value })}
            required
            inputMode="decimal"
            pattern="[0-9]+(\.[0-9]+)?"
          />
        </label>
        {error !== null && (
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={submitting}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
        >
          {submitting ? '创建中…' : '创建并进入'}
        </button>
      </form>
    </section>
  )
}
