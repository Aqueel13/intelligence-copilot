import { useEffect, useState } from 'react'
import { fetchHealth, type HealthResponse } from './api/client'

const SECTIONS = [
  { name: 'Watch', description: 'KPI monitors and alerts', milestone: 'M6' },
  { name: 'Investigate', description: 'Hypothesis-driven root-cause analysis', milestone: 'M4' },
  { name: 'Actions', description: 'Approvals, execution and audit trail', milestone: 'M5' },
]

type HealthState =
  | { kind: 'loading' }
  | { kind: 'ready'; data: HealthResponse }
  | { kind: 'error'; message: string }

function SystemStatus() {
  const [state, setState] = useState<HealthState>({ kind: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    fetchHealth(controller.signal)
      .then((data) => setState({ kind: 'ready', data }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return
        setState({ kind: 'error', message: err instanceof Error ? err.message : String(err) })
      })
    return () => controller.abort()
  }, [])

  const rows: [string, string, boolean][] =
    state.kind === 'ready'
      ? [
          ['API', `v${state.data.version} · ${state.data.environment}`, true],
          [
            'Database',
            state.data.database.ok
              ? `pgvector ${state.data.database.pgvector_version}`
              : (state.data.database.error ?? 'unavailable'),
            state.data.database.ok,
          ],
        ]
      : state.kind === 'error'
        ? [['API', state.message, false]]
        : []

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
        System status
      </h2>
      {state.kind === 'loading' && <p className="mt-3 text-sm text-slate-500">Checking…</p>}
      <dl className="mt-3 space-y-2">
        {rows.map(([label, value, ok]) => (
          <div key={label} className="flex items-center gap-3 text-sm">
            <span
              className={`h-2.5 w-2.5 rounded-full ${ok ? 'bg-emerald-500' : 'bg-rose-500'}`}
              aria-label={ok ? 'healthy' : 'unhealthy'}
            />
            <dt className="w-20 font-medium">{label}</dt>
            <dd className="text-slate-600">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

export default function App() {
  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-4">
          <div>
            <h1 className="text-lg font-semibold">Intelligence WatchDog</h1>
            <p className="text-xs text-slate-500">Watch · Investigate · Recommend · Act</p>
          </div>
        </div>
      </header>

      <main className="mx-auto grid max-w-5xl gap-6 px-4 py-8">
        <SystemStatus />
        <section className="grid gap-4 sm:grid-cols-3">
          {SECTIONS.map((s) => (
            <div
              key={s.name}
              className="rounded-xl border border-dashed border-slate-300 bg-white/60 p-5"
            >
              <div className="flex items-center justify-between">
                <h3 className="font-medium">{s.name}</h3>
                <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                  {s.milestone}
                </span>
              </div>
              <p className="mt-2 text-sm text-slate-500">{s.description}</p>
            </div>
          ))}
        </section>
      </main>
    </div>
  )
}
