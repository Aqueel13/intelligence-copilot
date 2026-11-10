import { useQuery } from '@tanstack/react-query'
import { NavLink, Outlet, useLocation } from 'react-router'
import { api } from '../api/client'
import { formatCount, formatDimensionValue, formatMonth } from '../lib/format'
import { useDomainScope } from '../lib/hooks'
import { monthsBetween } from '../lib/scope'

const NAV = [
  { to: '/overview', label: 'Overview', ready: true },
  { to: '/process', label: 'Process', ready: true },
  { to: '/knowledge', label: 'Knowledge', ready: true },
  { to: '/investigate', label: 'Investigate', ready: true },
  { to: '/actions', label: 'Actions', ready: false, milestone: 'M5' },
]

export default function Layout() {
  const { search } = useLocation()
  return (
    <div className="min-h-screen">
      <header className="border-b border-hairline bg-surface">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-4 py-3">
          <div className="flex items-center gap-8">
            <div>
              <div className="text-base font-semibold">Intelligence WatchDog</div>
              <div className="text-[11px] text-ink-muted">Watch · Investigate · Recommend · Act</div>
            </div>
            <nav aria-label="Main" className="flex gap-1">
              {NAV.map((n) =>
                n.ready ? (
                  <NavLink
                    key={n.to}
                    to={{ pathname: n.to, search }}
                    className={({ isActive }) =>
                      `rounded-md px-3 py-1.5 text-sm ${
                        isActive ? 'bg-ghost font-semibold text-ink' : 'text-ink-2 hover:bg-ghost'
                      }`
                    }
                  >
                    {n.label}
                  </NavLink>
                ) : (
                  <span
                    key={n.to}
                    className="cursor-not-allowed rounded-md px-3 py-1.5 text-sm text-ink-muted"
                    title={`Coming in ${n.milestone}`}
                    aria-disabled
                  >
                    {n.label}
                  </span>
                ),
              )}
            </nav>
          </div>
          <SystemStatus />
        </div>
      </header>
      <FilterBar />
      <main className="mx-auto max-w-7xl px-4 pb-16 pt-6">
        <Outlet />
      </main>
    </div>
  )
}

function SystemStatus() {
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 30_000 })
  const ok = health.data?.status === 'ok'
  const label = health.isPending ? 'Checking…' : ok ? 'All systems normal' : 'Degraded'
  return (
    <div className="flex items-center gap-2 text-xs text-ink-2" title={health.data?.database.error ?? ''}>
      <span
        aria-hidden
        className={`h-2 w-2 rounded-full ${health.isPending ? 'bg-axis' : ok ? 'bg-good' : 'bg-critical'}`}
      />
      {label}
      {health.data && <span className="text-ink-muted">v{health.data.version}</span>}
    </div>
  )
}

/** One filter row, above everything it scopes. Period first. */
function FilterBar() {
  const { domain, params, set, clear, active } = useDomainScope()
  const d = domain.data
  if (!d) return <div className="h-12 border-b border-hairline bg-surface" />
  const months = d.data_from && d.data_to ? monthsBetween(d.data_from, d.data_to) : []

  return (
    <div className="border-b border-hairline bg-surface">
      <div className="mx-auto flex max-w-7xl flex-wrap items-end gap-3 px-4 py-2.5">
        <Select
          label="From"
          value={params.get('from') ?? ''}
          onChange={(v) => set('from', v)}
          options={months.map((m) => ({ value: m, label: formatMonth(m) }))}
          allLabel="Start"
        />
        <Select
          label="To"
          value={params.get('to') ?? ''}
          onChange={(v) => set('to', v)}
          options={months.map((m) => ({ value: m, label: formatMonth(m) }))}
          allLabel="Latest"
        />
        <span className="mx-1 h-8 w-px bg-hairline" aria-hidden />
        {d.filters.map((f) => (
          <Select
            key={f.name}
            label={f.label}
            value={params.get(f.name) ?? ''}
            onChange={(v) => set(f.name, v)}
            options={(f.values ?? []).map((v) => ({ value: v, label: formatDimensionValue(v) }))}
            allLabel="All"
          />
        ))}
        {active > 0 && (
          <button onClick={clear} className="pb-1.5 text-xs text-ink-2 underline underline-offset-2 hover:text-ink">
            Clear filters
          </button>
        )}
        <div className="ml-auto pb-1.5 text-xs text-ink-muted">
          {d.display_name} · {formatCount(d.cases)} {d.case_label}s · SLA {d.sla_hours / 24} days
        </div>
      </div>
    </div>
  )
}

function Select({
  label,
  value,
  onChange,
  options,
  allLabel,
}: {
  label: string
  value: string
  onChange: (v: string | null) => void
  options: { value: string; label: string }[]
  allLabel: string
}) {
  return (
    <label className="flex flex-col gap-0.5">
      <span className="text-[11px] text-ink-muted">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value || null)}
        className={`rounded-md border border-hairline bg-surface px-2 py-1 text-xs ${
          value ? 'font-semibold text-ink' : 'text-ink-2'
        }`}
      >
        <option value="">{allLabel}</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  )
}
